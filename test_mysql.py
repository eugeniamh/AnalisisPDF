import mysql.connector

try:
    conn = mysql.connector.connect(
        host="127.0.0.1",
        port=3308,
        user="maru",
        password="Maru2018",  
        database="monitor_medios"
    )

    print("Conectado:", conn.is_connected())
    print("Servidor:", conn.get_server_info())

    conn.close()

except mysql.connector.Error as err:
    print("ERROR:", err)