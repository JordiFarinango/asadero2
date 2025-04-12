# app.py - Backend con Flask, PostgreSQL y Ruta Init Manual

import os
import json
import datetime
import psycopg2
import psycopg2.extras
import re
from decimal import Decimal, InvalidOperation
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# --- Configuración Inicial ---
app = Flask(__name__)
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print("¡ERROR FATAL! Variable de entorno DATABASE_URL no encontrada.")
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Conexión a Base de Datos ---
def get_db_connection():
    if not DATABASE_URL: print("Intento de conexión DB fallido: DATABASE_URL no configurada."); return None
    try: conn = psycopg2.connect(DATABASE_URL); return conn
    except psycopg2.OperationalError as e: print(f"Error conectando a la base de datos: {e}"); return None

# --- Inicialización de la Base de Datos ---
def init_db():
    # (Misma función init_db que antes - crea todas las tablas si no existen)
    # ... (Asegúrate de que el código completo de init_db esté aquí) ...
    print("Intentando inicializar/actualizar DB...")
    conn = get_db_connection()
    if not conn: print("No se pudo conectar a la DB para inicializar."); return False # Devolver False en error
    success = False
    try:
        with conn.cursor() as cur:
            print("Verificando tabla 'users'...")
            cur.execute("CREATE TABLE IF NOT EXISTS users (username VARCHAR(80) PRIMARY KEY, password_hash VARCHAR(255) NOT NULL, role VARCHAR(50) NOT NULL);")
            print("Verificando tabla 'inventory_presas'...")
            cur.execute("CREATE TABLE IF NOT EXISTS inventory_presas (nombre_presa VARCHAR(80) PRIMARY KEY, cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0), precio NUMERIC(10, 2) NOT NULL DEFAULT 1.00 CHECK (precio >= 0.00));")
            cur.execute("ALTER TABLE inventory_presas ADD COLUMN IF NOT EXISTS precio NUMERIC(10, 2) NOT NULL DEFAULT 1.00 CHECK (precio >= 0.00);")
            print("Verificando tabla 'inventory_productos'...")
            cur.execute("CREATE TABLE IF NOT EXISTS inventory_productos (nombre_producto VARCHAR(100) PRIMARY KEY, cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0), precio NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (precio >= 0.00));")
            cur.execute("ALTER TABLE inventory_productos ADD COLUMN IF NOT EXISTS precio NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (precio >= 0.00);")
            print("Verificando tabla 'inventory_info'...")
            cur.execute("CREATE TABLE IF NOT EXISTS inventory_info ( key VARCHAR(50) PRIMARY KEY, value_int INTEGER, value_numeric NUMERIC(10,2) );")
            print("Verificando tabla 'history'...")
            cur.execute("CREATE TABLE IF NOT EXISTS history ( id SERIAL PRIMARY KEY, timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, message TEXT NOT NULL );")
            print("Verificando tabla 'definitions'...")
            cur.execute("CREATE TABLE IF NOT EXISTS definitions ( key VARCHAR(50) PRIMARY KEY, value JSONB NOT NULL );")
            print("Verificando tabla 'sales'...")
            cur.execute("CREATE TABLE IF NOT EXISTS sales (sale_id SERIAL PRIMARY KEY, timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, total_amount NUMERIC(10, 2) NOT NULL CHECK (total_amount >= 0.00));")
            print("Verificando tabla 'sale_items'...")
            cur.execute("CREATE TABLE IF NOT EXISTS sale_items (item_id SERIAL PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(sale_id) ON DELETE CASCADE, item_type VARCHAR(50) NOT NULL, item_name VARCHAR(100) NOT NULL, display_name VARCHAR(150), quantity INTEGER NOT NULL CHECK (quantity > 0), price_per_item NUMERIC(10, 2) NOT NULL CHECK (price_per_item >= 0.00));")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sale_items_sale_id ON sale_items (sale_id);")
            cur.execute("DROP TABLE IF EXISTS inventory_presas;") # Eliminar tabla obsoleta si aún existe
            # --- Insertar/Actualizar datos iniciales ---
            # (Asegúrate de que esta lógica esté presente si la necesitas)
            # ...
            conn.commit()
            print("Base de datos inicializada/actualizada.")
            success = True
    except psycopg2.Error as e: print(f"Error durante inicialización/actualización de DB: {e}"); conn.rollback()
    finally:
        if conn: conn.close()
    return success

# --- NO llamar init_db() aquí al inicio, se llamará manualmente ---
# with app.app_context(): init_db()

# --- Funciones Auxiliares ---
def add_history_db(message, conn):
    # ... (igual que antes) ...
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO history (message) VALUES (%s)", (message,))
            cur.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY timestamp DESC LIMIT 100);")
        return True
    except psycopg2.Error as e: print(f"Error añadiendo historial a DB: {e}"); return False

# --- Rutas API ---
# (Todas las rutas /login, /api/inventory, /api/history, /api/add/*, /api/sell, /api/remove/*, /api/reports/sales, /api/update/price, /api/add/custom_combo, /api/remove/custom_combo
#  se mantienen igual que en la versión anterior flask_backend_v17_delete_combo)
#  Asegúrate de tenerlas todas aquí. Se omiten por brevedad.

@app.route('/')
def index(): return render_template('index.html')

# ... (pegar aquí TODAS las rutas API desde /login hasta /api/remove/custom_combo de la versión anterior) ...
# Ejemplo de una ruta (asegúrate de tener todas):
@app.route('/login', methods=['POST'])
def login():
    # ... (código de login) ...

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    # ... (código de get_inventory) ...

# ... y así sucesivamente para todas las rutas API ...

@app.route('/api/remove/custom_combo', methods=['POST'])
def remove_custom_combo():
    # ... (código de remove_custom_combo) ...


# --- NUEVA RUTA PARA INICIALIZAR DB MANUALMENTE ---
@app.route('/init-db-manually')
def manual_init_db_route():
    """Ruta temporal para forzar la inicialización de la DB."""
    # ¡¡¡ADVERTENCIA!!! Esta ruta debería eliminarse o protegerse en producción.
    print("Solicitud recibida en /init-db-manually")
    if init_db():
        return "Base de datos inicializada/verificada exitosamente.", 200
    else:
        return "Error al inicializar la base de datos. Revisa los logs del servidor.", 500

# --- Ejecutar la Aplicación ---
if __name__ == '__main__':
    print("Iniciando servidor Flask para DESARROLLO LOCAL...")
    # init_db() # Llamar aquí para desarrollo local si es necesario
    app.run(host='0.0.0.0', port=5000, debug=True)

