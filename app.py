from flask import Flask, render_template, request, redirect, url_for
import fitz
import os
import re
import mysql.connector
from collections import Counter
import pytesseract
from PIL import Image
import io
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"

PALABRAS_CLAVE = {
    "alto": ["Libia","corrupción", "desvío", "denuncia", "investigación", "fraude", "violencia", "amenaza", "escándalo"],
    "medio": ["gobernadora", "funcionario", "secretaría", "partido", "municipio", "conflicto", "diputado", "diputada"],
    "bajo": ["programa", "apoyo", "evento", "reunión", "declaración"]
}

SECRETARIAS = [
    "Secretaría de Gobierno",
    "Secretaría de Seguridad y Paz",
    "Secretaría de Salud",
    "Secretaría de Educación",
    "Secretaría de Finanzas",
    "Secretaría del Nuevo Comienzo",
    "Secretaría de Economía",
    "Secretaría de Obra Pública",
    "Secretaría del Campo",
    "Secretaría de Turismo",
    "DIF Estatal",
    "Fiscalía General del Estado",
    "Congreso del Estado",
]

ULTIMO_ANALISIS = {}

def get_db():
    conn = mysql.connector.connect(
        host="127.0.0.1",
        port=3308,
        user="maru",
        password="Maru2018",  # cambia si sí tienes contraseña
        database="monitor_medios",
        connection_timeout=5
    )

    if not conn.is_connected():
        raise Exception("No se pudo conectar a MySQL. Revisa puerto, usuario, contraseña o base de datos.")

    return conn

def init_db():
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documentos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nombre_archivo VARCHAR(255),
                total_paginas INT,
                total_alertas INT,
                riesgo_general VARCHAR(50),
                fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alertas (
                id INT AUTO_INCREMENT PRIMARY KEY,
                documento_id INT,
                pagina INT,
                palabra VARCHAR(150),
                cantidad INT,
                riesgo VARCHAR(50),
                contexto TEXT,
                FOREIGN KEY (documento_id) REFERENCES documentos(id)
            )
        """)

        conn.commit()
        cursor.close()
        conn.close()

        print("Base de datos inicializada correctamente.")

    except mysql.connector.Error as err:
        print("ERROR REAL DE MYSQL:", err)
        raise

def extraer_contexto(texto, palabra, margen=180):
    texto_lower = texto.lower()
    palabra_lower = palabra.lower()
    pos = texto_lower.find(palabra_lower)

    if pos == -1:
        return "No se encontró contexto."

    inicio = max(pos - margen, 0)
    fin = min(pos + len(palabra) + margen, len(texto))

    return texto[inicio:fin].replace("\n", " ").strip()

def detectar_personas(texto):
    patron = r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3}\b"
    nombres = re.findall(patron, texto)

    filtros = {
        "El Estado", "La Secretaría", "Los Estados", "San Miguel",
        "Guanajuato Capital", "Gobierno del Estado", "Congreso del Estado"
    }

    nombres_limpios = [n for n in nombres if n not in filtros and len(n) > 6]
    return nombres_limpios

def detectar_secretarias(texto):
    encontradas = []
    texto_lower = texto.lower()

    for secretaria in SECRETARIAS:
        if secretaria.lower() in texto_lower:
            encontradas.append(secretaria)

    return encontradas

def detectar_diputados(texto):
    resultados = []
    lineas = texto.split("\n")

    for linea in lineas:
        linea_lower = linea.lower()
        if "diputado" in linea_lower or "diputada" in linea_lower:
            resultados.append(linea.strip())

    return resultados
def extraer_texto_pagina(pagina):
    texto = pagina.get_text("text")

    if len(texto.strip()) > 30:
        return texto, "texto"

    pix = pagina.get_pixmap(dpi=200)
    img = Image.open(io.BytesIO(pix.tobytes("png")))

    # texto_ocr = pytesseract.image_to_string(img, lang="spa")
    texto_ocr = pytesseract.image_to_string(img, lang="eng")

    return texto_ocr, "ocr"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/procesar", methods=["POST"])
def procesar():
    global ULTIMO_ANALISIS

    archivo = request.files["pdf"]

    if archivo.filename == "":
        return "No se seleccionó archivo"

    ruta = os.path.join(app.config["UPLOAD_FOLDER"], archivo.filename)
    archivo.save(ruta)

    documento = fitz.open(ruta)

    alertas = []
    conteo_palabras = Counter()
    conteo_personas = Counter()
    conteo_secretarias = Counter()
    menciones_diputados = []

    total_paginas = len(documento)
    print("TOTAL DE PÁGINAS:", total_paginas)

    for num_pagina, pagina in enumerate(documento, start=1):
        # texto_original = pagina.get_text("text")
        texto_original, metodo = extraer_texto_pagina(pagina)

        print("Página:", num_pagina, "Método:", metodo, "Caracteres:", len(texto_original))

        if len(texto_original.strip()) < 30:
            print(f"Página {num_pagina} parece imagen o sin texto extraíble")
            

            print("Página:", num_pagina, "Caracteres extraídos:", len(texto_original))
            continue
        texto_lower = texto_original.lower()

        personas = detectar_personas(texto_original)
        conteo_personas.update(personas)

        secretarias = detectar_secretarias(texto_original)
        conteo_secretarias.update(secretarias)

        diputados = detectar_diputados(texto_original)
        for d in diputados:
            menciones_diputados.append({
                "pagina": num_pagina,
                "texto": d
            })

        for nivel, palabras in PALABRAS_CLAVE.items():
            for palabra in palabras:
                cantidad = texto_lower.count(palabra.lower())

                if cantidad > 0:
                    conteo_palabras[palabra] += cantidad

                    alertas.append({
                        "pagina": num_pagina,
                        "palabra": palabra,
                        "cantidad": cantidad,
                        "riesgo": nivel,
                        "contexto": extraer_contexto(texto_original, palabra)
                    })

    riesgo_general = "Bajo"

    if any(a["riesgo"] == "alto" for a in alertas):
        riesgo_general = "Alto"
    elif any(a["riesgo"] == "medio" for a in alertas):
        riesgo_general = "Medio"

    ULTIMO_ANALISIS = {
        "nombre_archivo": archivo.filename,
        "total_paginas": total_paginas,
        "total_alertas": len(alertas),
        "riesgo_general": riesgo_general,
        "alertas": alertas,
        "conteo_palabras": conteo_palabras.most_common(15),
        "conteo_personas": conteo_personas.most_common(15),
        "conteo_secretarias": conteo_secretarias.most_common(15),
        "menciones_diputados": menciones_diputados[:20]
    }

    return render_template("dashboard.html", **ULTIMO_ANALISIS)

@app.route("/guardar", methods=["POST"])
def guardar():
    init_db()

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO documentos (nombre_archivo, total_paginas, total_alertas, riesgo_general)
        VALUES (?, ?, ?, ?)
    """, (
        ULTIMO_ANALISIS["nombre_archivo"],
        ULTIMO_ANALISIS["total_paginas"],
        ULTIMO_ANALISIS["total_alertas"],
        ULTIMO_ANALISIS["riesgo_general"]
    ))

    documento_id = cursor.lastrowid

    for alerta in ULTIMO_ANALISIS["alertas"]:
        cursor.execute("""
            INSERT INTO alertas (documento_id, pagina, palabra, cantidad, riesgo, contexto)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            documento_id,
            alerta["pagina"],
            alerta["palabra"],
            alerta["cantidad"],
            alerta["riesgo"],
            alerta["contexto"]
        ))

    conn.commit()
    conn.close()

    return redirect(url_for("index"))

if __name__ == "__main__":
    init_db()
    app.run(debug=True)