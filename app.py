# app.py - Backend con Flask y PostgreSQL para Railway

import os
import json
import datetime
import psycopg2 # Librería para PostgreSQL
import psycopg2.extras # Para usar diccionarios en resultados
from urllib.parse import urlparse # Para leer DATABASE_URL
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# --- Configuración Inicial ---
app = Flask(__name__)
# Leer la URL de la base de datos desde las variables de entorno (Railway la inyecta)
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print("¡ADVERTENCIA! Variable de entorno DATABASE_URL no encontrada.")
    # Podrías poner una URL de fallback para desarrollo local si quieres,
    # pero es mejor configurar la variable de entorno localmente.
    # Ejemplo: DATABASE_URL = "postgresql://user:password@host:port/database"

CORS(app, resources={r"/*": {"origins": "*"}}) # Permitir todo por ahora

# --- Conexión a Base de Datos ---

def get_db_connection():
    """Establece conexión con la base de datos PostgreSQL."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except psycopg2.OperationalError as e:
        print(f"Error conectando a la base de datos: {e}")
        return None

# --- Inicialización de la Base de Datos ---

def init_db():
    """Crea las tablas necesarias si no existen."""
    conn = get_db_connection()
    if not conn:
        print("No se pudo conectar a la DB para inicializar.")
        return

    try:
        with conn.cursor() as cur:
            # Crear tabla de usuarios (si no existe)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username VARCHAR(80) PRIMARY KEY,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(50) NOT NULL
                );
            """)
            # Crear tabla de inventario_presas (si no existe)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_presas (
                    nombre_presa VARCHAR(80) PRIMARY KEY,
                    cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0)
                );
            """)
            # Crear tabla de inventario_productos (si no existe)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_productos (
                    nombre_producto VARCHAR(100) PRIMARY KEY,
                    cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0)
                );
            """)
             # Crear tabla de inventario_info (para pollos enteros, etc. si es necesario)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_info (
                    key VARCHAR(50) PRIMARY KEY,
                    value INTEGER NOT NULL DEFAULT 0
                );
            """)
            # Crear tabla de historial (si no existe)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    message TEXT NOT NULL
                );
            """)
            # Crear tabla de combos (si no existe) - Guardar como JSON por simplicidad
            cur.execute("""
                 CREATE TABLE IF NOT EXISTS definitions (
                     key VARCHAR(50) PRIMARY KEY,
                     value JSONB NOT NULL
                 );
             """)

            # --- Insertar datos iniciales si las tablas estaban vacías ---
            # Usuarios (solo si no existen)
            cur.execute("SELECT COUNT(*) FROM users;")
            if cur.fetchone()[0] == 0:
                print("Insertando usuarios iniciales...")
                initial_users = [
                    ('admin', generate_password_hash("admin123"), 'admin'),
                    ('venta', generate_password_hash("venta123"), 'vendedor')
                ]
                cur.executemany("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)", initial_users)

            # Presas (solo si no existen) - Asumiendo que empezamos con 0
            presas_base = ["pechuga", "muslo", "ala", "pierna"]
            for p in presas_base:
                 cur.execute("INSERT INTO inventory_presas (nombre_presa, cantidad) VALUES (%s, %s) ON CONFLICT (nombre_presa) DO NOTHING;", (p, 0))

            # Productos (solo si no existen)
            cur.execute("SELECT COUNT(*) FROM inventory_productos;")
            if cur.fetchone()[0] == 0:
                 print("Insertando productos iniciales...")
                 initial_productos = [('Papas', 10), ('Gaseosa', 15), ('Ají', 5)]
                 cur.executemany("INSERT INTO inventory_productos (nombre_producto, cantidad) VALUES (%s, %s)", initial_productos)

            # Info (pollos enteros)
            cur.execute("INSERT INTO inventory_info (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;", ('pollosEnteros', 0))

             # Definiciones (Combos y PresasPorPollo) - Guardar como JSON
            initial_combos = {
                "combo_1_8_pechuga": { "pechuga": 1 }, "combo_1_8_muslo": { "muslo": 1 },
                "combo_1_8_ala": { "ala": 1 }, "combo_1_8_pierna": { "pierna": 1 },
                "combo_1_4_pechuga_ala": { "pechuga": 1, "ala": 1 }, "combo_1_4_muslo_pierna": { "muslo": 1, "pierna": 1 },
                "combo_1_2": { "pechuga": 1, "ala": 1, "muslo": 1, "pierna": 1 },
                "combo_entero": { "pechuga": 2, "ala": 2, "muslo": 2, "pierna": 2 }
            }
            initial_presas_por_pollo = { "pechuga": 2, "muslo": 2, "ala": 2, "pierna": 2 }

            cur.execute("INSERT INTO definitions (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;",
                        ('combos', json.dumps(initial_combos)))
            cur.execute("INSERT INTO definitions (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;",
                        ('presasPorPollo', json.dumps(initial_presas_por_pollo)))

            # Historial inicial
            cur.execute("SELECT COUNT(*) FROM history;")
            if cur.fetchone()[0] == 0:
                 print("Insertando historial inicial...")
                 ts = datetime.datetime.now(datetime.timezone.utc)
                 cur.execute("INSERT INTO history (timestamp, message) VALUES (%s, %s)", (ts, "Sistema inicializado."))

            conn.commit() # Guardar cambios
            print("Base de datos inicializada/verificada.")
    except psycopg2.Error as e:
        print(f"Error durante inicialización de DB: {e}")
        if conn: conn.rollback() # Revertir cambios si hay error
    finally:
        if conn: conn.close() # Siempre cerrar conexión

# Llamar a init_db() una vez al inicio para asegurar que las tablas existan
init_db()

# --- Funciones Auxiliares de Base de Datos ---

def add_history_db(message, conn=None):
    """Agrega una entrada al historial en la base de datos."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if not conn: return False
        close_conn = True

    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO history (message) VALUES (%s)", (message,))
            # Limitar historial (opcional, se puede hacer con SQL también)
            cur.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY timestamp DESC LIMIT 100);")
            conn.commit()
        return True
    except psycopg2.Error as e:
        print(f"Error añadiendo historial a DB: {e}")
        if conn and not conn.closed: conn.rollback()
        return False
    finally:
        if close_conn and conn and not conn.closed: conn.close()


# --- Rutas de la Aplicación ---

@app.route('/')
def index(): return render_template('index.html')

# --- Rutas de la API ---

@app.route('/login', methods=['POST'])
def login():
    req_data = request.get_json(); username = req_data.get('username'); password_attempt = req_data.get('password')
    if not username or not password_attempt: return jsonify({"success": False, "message": "Faltan datos."}), 400

    conn = get_db_connection(); user_info = None
    if not conn: return jsonify({"success": False, "message": "Error de conexión DB."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT password_hash, role FROM users WHERE username = %s", (username,))
            user_info = cur.fetchone()

        if user_info and check_password_hash(user_info['password_hash'], password_attempt):
            print(f"Login OK: {username}"); return jsonify({"success": True, "role": user_info['role']})
        else:
            print(f"Login FAIL: {username}"); return jsonify({"success": False, "message": "Credenciales incorrectas."}), 401
    except psycopg2.Error as e:
        print(f"Error DB en login: {e}"); return jsonify({"success": False, "message": "Error interno del servidor."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    conn = get_db_connection(); inventory_data = {}
    if not conn: return jsonify({"success": False, "message": "Error de conexión DB."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Obtener presas
            cur.execute("SELECT nombre_presa, cantidad FROM inventory_presas")
            presas = {row['nombre_presa']: row['cantidad'] for row in cur.fetchall()}
            # Obtener productos
            cur.execute("SELECT nombre_producto, cantidad FROM inventory_productos")
            productos = {row['nombre_producto']: row['cantidad'] for row in cur.fetchall()}
            # Obtener pollos enteros
            cur.execute("SELECT value FROM inventory_info WHERE key = 'pollosEnteros'")
            result = cur.fetchone()
            pollos_enteros = result['value'] if result else 0
            # Obtener definiciones
            cur.execute("SELECT key, value FROM definitions")
            definitions = {row['key']: row['value'] for row in cur.fetchall()}

            inventory_data = {
                "inventory": {"pollosEnteros": pollos_enteros, "presas": presas, "productos": productos},
                "combos": definitions.get('combos', {}),
                "presasPorPollo": definitions.get('presasPorPollo', {})
            }
        return jsonify(inventory_data)
    except psycopg2.Error as e:
        print(f"Error DB obteniendo inventario: {e}"); return jsonify({"success": False, "message": "Error interno."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/history', methods=['GET'])
def get_history():
    conn = get_db_connection(); history_list = []
    if not conn: return jsonify({"success": False, "message": "Error de conexión DB."}), 500
    try:
        with conn.cursor() as cur:
            # Obtener los últimos 100 mensajes, formateados
            cur.execute("SELECT timestamp, message FROM history ORDER BY timestamp DESC LIMIT 100")
            history_list = [f"[{row[0].strftime('%Y-%m-%d %H:%M:%S')}] {row[1]}" for row in cur.fetchall()]
        return jsonify({"history": history_list})
    except psycopg2.Error as e:
        print(f"Error DB obteniendo historial: {e}"); return jsonify({"success": False, "message": "Error interno."}), 500
    finally:
        if conn: conn.close()

# --- RUTAS AGREGAR ---
@app.route('/api/add/pollos', methods=['POST'])
def add_pollos():
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Error de conexión DB."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Obtener definición de presas por pollo
            cur.execute("SELECT value FROM definitions WHERE key = 'presasPorPollo'")
            result = cur.fetchone()
            presas_por_pollo = result['value'] if result else {}

            # Actualizar contador de pollos
            cur.execute("INSERT INTO inventory_info (key, value) VALUES ('pollosEnteros', %s) ON CONFLICT (key) DO UPDATE SET value = inventory_info.value + EXCLUDED.value;", (cantidad,))

            # Actualizar presas
            for presa, cant_pp in presas_por_pollo.items():
                cur.execute("INSERT INTO inventory_presas (nombre_presa, cantidad) VALUES (%s, %s) ON CONFLICT (nombre_presa) DO UPDATE SET cantidad = inventory_presas.cantidad + EXCLUDED.cantidad;", (presa, cantidad * cant_pp))

            # Añadir historial
            log_msg = f"ENTRADA: {cantidad} pollos enteros agregados."
            cur.execute("INSERT INTO history (message) VALUES (%s)", (log_msg,))
            conn.commit() # Guardar todos los cambios
            print(f"Agregados {cantidad} pollos.")
            return jsonify({"success": True, "message": f"{cantidad} pollos agregados."})
    except psycopg2.Error as e:
        print(f"Error DB agregando pollos: {e}"); conn.rollback()
        return jsonify({"success": False, "message": "Error al actualizar inventario."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/add/presas', methods=['POST'])
def add_presas():
    req_data = request.get_json(); tipo = req_data.get('type', '').lower(); cantidad = req_data.get('quantity')
    if not tipo or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Error de conexión DB."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
             # Verificar si tipo existe (opcional, pero bueno)
             cur.execute("SELECT value FROM definitions WHERE key = 'presasPorPollo'")
             result = cur.fetchone()
             presas_validas = result['value'].keys() if result else []
             if tipo not in presas_validas: return jsonify({"success": False, "message": f"Tipo '{tipo}' inválido."}), 400

             # Actualizar presa
             cur.execute("INSERT INTO inventory_presas (nombre_presa, cantidad) VALUES (%s, %s) ON CONFLICT (nombre_presa) DO UPDATE SET cantidad = inventory_presas.cantidad + EXCLUDED.cantidad;", (tipo, cantidad))

             # Añadir historial
             log_msg = f"ENTRADA: {cantidad} {tipo}(s) individuales agregadas."
             cur.execute("INSERT INTO history (message) VALUES (%s)", (log_msg,))
             conn.commit()
             print(f"Agregadas {cantidad} {tipo}(s).")
             return jsonify({"success": True, "message": f"{cantidad} {tipo}(s) agregados."})
    except psycopg2.Error as e:
        print(f"Error DB agregando presas: {e}"); conn.rollback()
        return jsonify({"success": False, "message": "Error al actualizar inventario."}), 500
    finally:
        if conn: conn.close()


@app.route('/api/add/producto', methods=['POST'])
def add_producto():
    req_data = request.get_json(); nombre = req_data.get('name', '').strip().capitalize(); cantidad = req_data.get('quantity')
    if not nombre or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Error de conexión DB."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Actualizar producto
            cur.execute("INSERT INTO inventory_productos (nombre_producto, cantidad) VALUES (%s, %s) ON CONFLICT (nombre_producto) DO UPDATE SET cantidad = inventory_productos.cantidad + EXCLUDED.cantidad RETURNING cantidad;", (nombre, cantidad))
            result = cur.fetchone()
            stock_actual = result['cantidad'] if result else 'N/A'

            # Añadir historial
            log_msg = f"ENTRADA PRODUCTO: {cantidad} {nombre} (Stock: {stock_actual})."
            cur.execute("INSERT INTO history (message) VALUES (%s)", (log_msg,))
            conn.commit()
            print(f"Producto: {cantidad} x {nombre}")
            return jsonify({"success": True, "message": f"{cantidad} '{nombre}' agregados."})
    except psycopg2.Error as e:
        print(f"Error DB agregando producto: {e}"); conn.rollback()
        return jsonify({"success": False, "message": "Error al actualizar inventario."}), 500
    finally:
        if conn: conn.close()

# --- RUTAS VENDER Y ELIMINAR ---
@app.route('/api/sell', methods=['POST'])
def sell_cart():
    req_data = request.get_json(); cart = req_data.get('cart')
    if not isinstance(cart, list) or not cart: return jsonify({"success": False, "message": "Carrito inválido."}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Error de conexión DB."}), 500

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Cargar definiciones y stock actual DENTRO de la transacción
            cur.execute("SELECT value FROM definitions WHERE key = 'combos'")
            combos_def = cur.fetchone()['value'] if cur.rowcount > 0 else {}
            cur.execute("SELECT nombre_presa, cantidad FROM inventory_presas")
            current_presas = {row['nombre_presa']: row['cantidad'] for row in cur.fetchall()}
            cur.execute("SELECT nombre_producto, cantidad FROM inventory_productos")
            current_productos = {row['nombre_producto']: row['cantidad'] for row in cur.fetchall()}

            requerimientos = {"presas": {}, "productos": {}}; items_faltantes = []; stock_suficiente = True

            # Calcular requerimientos
            for item in cart:
                tipo = item.get('tipo'); nombre = item.get('nombre'); cantidad = item.get('cantidad', 0); display_name = item.get('display', nombre)
                if cantidad <= 0: continue
                if tipo == 'combo':
                    if nombre not in combos_def: stock_suficiente = False; items_faltantes.append(f"Combo '{display_name}'?"); continue
                    for presa, cant_req in combos_def[nombre].items(): requerimientos['presas'][presa] = requerimientos['presas'].get(presa, 0) + cant_req * cantidad
                elif tipo == 'presa': requerimientos['presas'][nombre] = requerimientos['presas'].get(nombre, 0) + cantidad
                elif tipo == 'producto': requerimientos['productos'][nombre] = requerimientos['productos'].get(nombre, 0) + cantidad
                else: stock_suficiente = False; items_faltantes.append(f"Tipo? '{display_name}'")

            # Comprobar stock
            for p, cR in requerimientos['presas'].items():
                if current_presas.get(p, 0) < cR: stock_suficiente = False; items_faltantes.append(f"{p}({cR}/{current_presas.get(p, 0)})")
            for p, cR in requerimientos['productos'].items():
                 if current_productos.get(p, 0) < cR: stock_suficiente = False; items_faltantes.append(f"{p}({cR}/{current_productos.get(p, 0)})")

            if not stock_suficiente:
                print(f"Venta fallida stock: {items_faltantes}"); conn.rollback() # Importante revertir si falla
                return jsonify({"success": False, "message": f"Stock insuficiente: {', '.join(items_faltantes)}"}), 400

            # Si hay stock, descontar
            print("Stock suficiente. Descontando...")
            for p, cR in requerimientos['presas'].items():
                cur.execute("UPDATE inventory_presas SET cantidad = cantidad - %s WHERE nombre_presa = %s", (cR, p))
            for p, cR in requerimientos['productos'].items():
                cur.execute("UPDATE inventory_productos SET cantidad = cantidad - %s WHERE nombre_producto = %s", (cR, p))

            # Generar log y añadirlo
            resumen_display = ', '.join([f"{item['cantidad']}x{item.get('display', item['nombre'])}" for item in cart])
            log_msg = f"VENTA CARRITO ({len(cart)} items): {resumen_display}."
            cur.execute("INSERT INTO history (message) VALUES (%s)", (log_msg,))

            # Guardar TODOS los cambios
            conn.commit()
            print(f"Venta procesada: {resumen_display}")
            return jsonify({"success": True, "message": "Venta procesada!"})

    except psycopg2.Error as e:
        print(f"Error DB procesando venta: {e}");
        if conn: conn.rollback() # Revertir en caso de error DB
        return jsonify({"success": False, "message": "Error interno al procesar venta."}), 500
    finally:
        if conn: conn.close()


@app.route('/api/remove/pollos', methods=['POST'])
def remove_pollos():
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Error de conexión DB."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT value FROM definitions WHERE key = 'presasPorPollo'")
            presas_por_pollo = cur.fetchone()['value'] if cur.rowcount > 0 else {}
            cur.execute("SELECT nombre_presa, cantidad FROM inventory_presas")
            current_presas = {row['nombre_presa']: row['cantidad'] for row in cur.fetchall()}

            presas_necesarias = {}; stock_presas_suficiente = True
            for p, cPP in presas_por_pollo.items():
                req = cantidad * cPP
                if current_presas.get(p, 0) < req: stock_presas_suficiente = False; presas_necesarias[p] = f"Req:{req}/Disp:{current_presas.get(p, 0)}"
            if not stock_presas_suficiente: msg = f"Presas insuficientes: {presas_necesarias}"; print(msg); conn.rollback(); return jsonify({"success": False, "message": msg}), 400

            cur.execute("UPDATE inventory_info SET value = value - %s WHERE key = 'pollosEnteros' AND value >= %s", (cantidad, cantidad))
            if cur.rowcount == 0: print("Advertencia: No se pudo descontar pollosEnteros o ya era 0.") # Opcional: manejar si no se pudo descontar

            for p, cPP in presas_por_pollo.items():
                cur.execute("UPDATE inventory_presas SET cantidad = cantidad - %s WHERE nombre_presa = %s AND cantidad >= %s", (cantidad * cPP, p, cantidad * cPP))
                if cur.rowcount == 0: raise psycopg2.Error(f"No se pudo descontar stock suficiente para {p}") # Lanzar error si falla un update

            log_msg = f"ELIMINACIÓN: {cantidad} pollos enteros (merma)."
            cur.execute("INSERT INTO history (message) VALUES (%s)", (log_msg,))
            conn.commit()
            print(f"Eliminados {cantidad} pollos (merma).")
            return jsonify({"success": True, "message": f"{cantidad} pollos eliminados." })
    except psycopg2.Error as e:
        print(f"Error DB eliminando pollos: {e}"); conn.rollback()
        return jsonify({"success": False, "message": "Error al eliminar pollos."}), 500
    finally:
        if conn: conn.close()


@app.route('/api/remove/presas', methods=['POST'])
def remove_presas():
    req_data = request.get_json(); tipo = req_data.get('type', '').lower(); cantidad = req_data.get('quantity')
    if not tipo or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Error de conexión DB."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("UPDATE inventory_presas SET cantidad = cantidad - %s WHERE nombre_presa = %s AND cantidad >= %s", (cantidad, tipo, cantidad))
            if cur.rowcount == 0: # Si no se actualizó ninguna fila, es porque no existía o no había stock
                 cur.execute("SELECT cantidad FROM inventory_presas WHERE nombre_presa = %s", (tipo,))
                 stock_actual = cur.fetchone()
                 stock_disp = stock_actual['cantidad'] if stock_actual else 0
                 msg = f"Stock insuf. o presa '{tipo}' no existe (Disp: {stock_disp})"
                 conn.rollback(); return jsonify({"success": False, "message": msg}), 400

            log_msg = f"ELIMINACIÓN: {cantidad} {tipo}(s) (merma)."
            cur.execute("INSERT INTO history (message) VALUES (%s)", (log_msg,))
            conn.commit()
            print(f"Eliminadas {cantidad} {tipo}(s) (merma).")
            return jsonify({"success": True, "message": f"{cantidad} {tipo}(s) eliminados." })
    except psycopg2.Error as e:
        print(f"Error DB eliminando presas: {e}"); conn.rollback()
        return jsonify({"success": False, "message": "Error al eliminar presas."}), 500
    finally:
        if conn: conn.close()


@app.route('/api/remove/producto', methods=['POST'])
def remove_producto():
    req_data = request.get_json(); nombre = req_data.get('name', '').strip().capitalize(); cantidad = req_data.get('quantity')
    if not nombre or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Error de conexión DB."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("UPDATE inventory_productos SET cantidad = cantidad - %s WHERE nombre_producto = %s AND cantidad >= %s RETURNING cantidad", (cantidad, nombre, cantidad))
            result = cur.fetchone()
            if result is None: # Si no se actualizó (no existe o no hay stock)
                cur.execute("SELECT cantidad FROM inventory_productos WHERE nombre_producto = %s", (nombre,))
                stock_actual = cur.fetchone()
                stock_disp = stock_actual['cantidad'] if stock_actual else 0
                msg = f"Stock insuf. o producto '{nombre}' no existe (Disp: {stock_disp})"
                conn.rollback(); return jsonify({"success": False, "message": msg}), 400

            stock_restante = result['cantidad']
            log_msg = f"ELIMINACIÓN PRODUCTO: {cantidad} {nombre} (merma). Stock: {stock_restante}."
            cur.execute("INSERT INTO history (message) VALUES (%s)", (log_msg,))
            conn.commit()
            print(f"Eliminado producto: {cantidad} x {nombre} (merma).")
            return jsonify({"success": True, "message": f"{cantidad} '{nombre}' eliminados." })
    except psycopg2.Error as e:
        print(f"Error DB eliminando producto: {e}"); conn.rollback()
        return jsonify({"success": False, "message": "Error al eliminar producto."}), 500
    finally:
        if conn: conn.close()


# --- Ejecutar la Aplicación ---
if __name__ == '__main__':
    print("Iniciando servidor Flask para DESARROLLO...")
    # Asegúrate de tener psycopg2-binary instalado: pip install psycopg2-binary
    app.run(host='0.0.0.0', port=5000, debug=True)

