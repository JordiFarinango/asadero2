# app.py - Backend Completo con Flask, PostgreSQL, Presas Generales y Funciones Adicionales

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
# Configurar CORS - Permitir todos los orígenes por ahora (*)
# En producción, reemplazar '*' con la URL de Netlify: "https://tu-sitio.netlify.app"
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Constantes ---
DEFAULT_PRESA_PRICE = Decimal("1.25") # Precio por defecto para una presa genérica
PRESAS_KEY = 'presas_total' # Clave usada en tabla inventory_info
PRESA_PRICE_KEY = 'presa_precio_default' # Clave usada en tabla inventory_info
PRESAS_PER_POLLO_KEY = 'presas_por_pollo_total' # Clave usada en tabla definitions
COMBOS_KEY = 'combos' # Clave usada en tabla definitions

# --- Conexión a Base de Datos ---
def get_db_connection():
    """Establece conexión con la base de datos PostgreSQL."""
    if not DATABASE_URL:
        print("Intento de conexión DB fallido: DATABASE_URL no configurada.")
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        # print("Conexión a DB establecida.") # Log opcional
        return conn
    except psycopg2.OperationalError as e:
        print(f"Error conectando a la base de datos: {e}")
        return None

# --- Inicialización de la Base de Datos ---
def init_db():
    """Crea/Actualiza las tablas necesarias si no existen."""
    print("Intentando inicializar/actualizar DB para Presa General...")
    conn = get_db_connection()
    if not conn:
        print("No se pudo conectar a la DB para inicializar.")
        return

    try:
        with conn.cursor() as cur:
            # Crear tabla de usuarios
            print("Verificando tabla 'users'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username VARCHAR(80) PRIMARY KEY,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(50) NOT NULL
                );
            """)
            # Crear tabla de productos
            print("Verificando tabla 'inventory_productos'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_productos (
                    nombre_producto VARCHAR(100) PRIMARY KEY,
                    cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0),
                    precio NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (precio >= 0.00)
                );
            """)
            # Asegurar columna precio en productos
            cur.execute("""
                ALTER TABLE inventory_productos ADD COLUMN IF NOT EXISTS precio NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (precio >= 0.00);
            """)
            # Crear tabla de info general
            print("Verificando tabla 'inventory_info'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_info (
                    key VARCHAR(50) PRIMARY KEY,
                    value_int INTEGER,
                    value_numeric NUMERIC(10,2)
                );
            """)
            # Crear tabla de historial simple
            print("Verificando tabla 'history'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    message TEXT NOT NULL
                );
            """)
            # Crear tabla de definiciones (combos, etc.)
            print("Verificando tabla 'definitions'...")
            cur.execute("""
                 CREATE TABLE IF NOT EXISTS definitions (
                     key VARCHAR(50) PRIMARY KEY,
                     value JSONB NOT NULL
                 );
             """)
            # Crear tabla de ventas
            print("Verificando tabla 'sales'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sales (
                    sale_id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    total_amount NUMERIC(10, 2) NOT NULL CHECK (total_amount >= 0.00)
                );
            """)
            # Crear tabla de items de venta
            print("Verificando tabla 'sale_items'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sale_items (
                    item_id SERIAL PRIMARY KEY,
                    sale_id INTEGER NOT NULL REFERENCES sales(sale_id) ON DELETE CASCADE,
                    item_type VARCHAR(50) NOT NULL, -- 'combo', 'producto', 'presa'
                    item_name VARCHAR(100) NOT NULL, -- Clave interna o nombre
                    display_name VARCHAR(150), -- Nombre legible
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    price_per_item NUMERIC(10, 2) NOT NULL CHECK (price_per_item >= 0.00) -- Precio al vender
                );
            """)
            # Crear índice para eficiencia
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_sale_items_sale_id ON sale_items (sale_id);
            """)
            # Eliminar tabla obsoleta 'inventory_presas'
            cur.execute("DROP TABLE IF EXISTS inventory_presas;")
            print("Tabla obsoleta 'inventory_presas' eliminada si existía.")

            # --- Insertar/Actualizar datos iniciales ---
            # Usuarios
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING;", ('admin', generate_password_hash("admin123"), 'admin'))
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING;", ('venta', generate_password_hash("venta123"), 'vendedor'))

            # Productos
            initial_productos = [('Papas', 0, Decimal('1.50')), ('Gaseosa', 0, Decimal('0.75')), ('Ají', 0, Decimal('0.50'))]
            for nombre, cant, precio in initial_productos:
                cur.execute("INSERT INTO inventory_productos (nombre_producto, cantidad, precio) VALUES (%s, %s, %s) ON CONFLICT (nombre_producto) DO NOTHING;", (nombre, cant, precio))

            # Info General
            cur.execute("INSERT INTO inventory_info (key, value_int) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;", ('pollosEnteros', 0))
            cur.execute("INSERT INTO inventory_info (key, value_int) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;", (PRESAS_KEY, 0)) # Total presas
            cur.execute("INSERT INTO inventory_info (key, value_numeric) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;", (PRESA_PRICE_KEY, DEFAULT_PRESA_PRICE)) # Precio presa

            # Definiciones
            initial_presas_por_pollo_total = 8
            cur.execute("INSERT INTO definitions (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;",
                        (PRESAS_PER_POLLO_KEY, json.dumps(initial_presas_por_pollo_total)))
            initial_combos = {
                "combo_1_8": { "presas_necesarias": 1, "productos": {}, "precio": "2.00" },
                "combo_1_4": { "presas_necesarias": 2, "productos": {}, "precio": "3.50" },
                "combo_1_2": { "presas_necesarias": 4, "productos": {}, "precio": "6.50" },
                "combo_entero": { "presas_necesarias": initial_presas_por_pollo_total, "productos": {}, "precio": "12.00" }
            }
            cur.execute("INSERT INTO definitions (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;",
                        (COMBOS_KEY, json.dumps(initial_combos)))

            # Historial inicial
            cur.execute("SELECT COUNT(*) FROM history;")
            if cur.fetchone()[0] == 0:
                 ts = datetime.datetime.now(datetime.timezone.utc)
                 cur.execute("INSERT INTO history (timestamp, message) VALUES (%s, %s)", (ts, "Sistema inicializado con DB (presas generales)."))

            conn.commit()
            print("Base de datos inicializada/actualizada (con presas generales).")
    except psycopg2.Error as e: print(f"Error durante inicialización/actualización de DB: {e}"); conn.rollback()
    finally:
        if conn: conn.close()

# Llamar a init_db() al inicio
with app.app_context():
    init_db()

# --- Funciones Auxiliares ---
def add_history_db(message, conn):
    """Agrega una entrada al historial simple en la base de datos."""
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO history (message) VALUES (%s)", (message,))
            cur.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY timestamp DESC LIMIT 100);")
        return True
    except psycopg2.Error as e: print(f"Error añadiendo historial a DB: {e}"); return False

# --- Rutas API ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    req_data = request.get_json(); username = req_data.get('username'); password_attempt = req_data.get('password')
    if not username or not password_attempt: return jsonify({"success": False, "message": "Faltan datos."}), 400
    conn = get_db_connection(); user_info = None;
    if not conn: return jsonify({"success": False, "message": "Error DB (L1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT password_hash, role FROM users WHERE username = %s", (username,))
            user_info = cur.fetchone()
        if user_info and user_info['password_hash'] and check_password_hash(user_info['password_hash'], password_attempt):
            print(f"Login OK: {username}"); return jsonify({"success": True, "role": user_info.get('role', 'vendedor')})
        else:
            print(f"Login FAIL: {username}"); return jsonify({"success": False, "message": "Credenciales incorrectas."}), 401
    except psycopg2.Error as e: print(f"Error DB login: {e}"); return jsonify({"success": False, "message": "Error interno (L2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (I1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT key, value_int, value_numeric FROM inventory_info WHERE key IN (%s, %s, %s)", (PRESAS_KEY, PRESA_PRICE_KEY, 'pollosEnteros'))
            info_data = {row['key']: row['value_int'] if row['value_int'] is not None else float(row['value_numeric']) for row in cur.fetchall()}
            presas_total = info_data.get(PRESAS_KEY, 0)
            presa_precio = info_data.get(PRESA_PRICE_KEY, float(DEFAULT_PRESA_PRICE))
            pollos_enteros = info_data.get('pollosEnteros', 0)
            cur.execute("SELECT nombre_producto, cantidad, precio FROM inventory_productos")
            productos = {row['nombre_producto']: {"cantidad": row['cantidad'], "precio": float(row['precio'])} for row in cur.fetchall()}
            cur.execute("SELECT key, value FROM definitions")
            definitions = {row['key']: row['value'] for row in cur.fetchall()}
            combos_def = definitions.get(COMBOS_KEY, {})
            presas_por_pollo_total = definitions.get(PRESAS_PER_POLLO_KEY, 8)
            combos_con_precio_float = {}
            for key, combo_data in combos_def.items():
                try: combos_con_precio_float[key] = { "presas_necesarias": combo_data.get("presas_necesarias", 0), "productos": combo_data.get("productos", {}), "precio": float(combo_data.get("precio", "0.00")) }
                except (ValueError, TypeError): combos_con_precio_float[key] = { "presas_necesarias": 0, "productos": {}, "precio": 0.00 }
            inventory_data = { "inventory": {"pollosEnteros": pollos_enteros, "presas_total": presas_total, "presa_precio_default": presa_precio, "productos": productos}, "combos": combos_con_precio_float, "presasPorPolloTotal": presas_por_pollo_total }
        return jsonify(inventory_data)
    except psycopg2.Error as e: print(f"Error DB get_inventory: {e}"); return jsonify({"success": False, "message": "Error interno (I2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/history', methods=['GET'])
def get_history():
    conn = get_db_connection(); history_list = []
    if not conn: return jsonify({"success": False, "message": "Error DB (H1)."}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT timestamp, message FROM history ORDER BY timestamp DESC LIMIT 100")
            history_list = [f"[{row[0].strftime('%Y-%m-%d %H:%M:%S')}] {row[1]}" for row in cur.fetchall()]
        return jsonify({"history": history_list})
    except psycopg2.Error as e: print(f"Error DB get_history: {e}"); return jsonify({"success": False, "message": "Error interno (H2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/add/pollos', methods=['POST'])
def add_pollos():
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (APo1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT value FROM definitions WHERE key = %s", (PRESAS_PER_POLLO_KEY,))
            result = cur.fetchone(); presas_pp = result['value'] if result else 8
            cur.execute("INSERT INTO inventory_info (key, value_int) VALUES ('pollosEnteros', %s) ON CONFLICT (key) DO UPDATE SET value_int = inventory_info.value_int + EXCLUDED.value_int;", (cantidad,))
            presas_a_sumar = cantidad * presas_pp
            cur.execute("INSERT INTO inventory_info (key, value_int) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value_int = inventory_info.value_int + EXCLUDED.value_int;", (PRESAS_KEY, presas_a_sumar))
            log_msg = f"ENTRADA: {cantidad} pollos enteros agregados ({presas_a_sumar} presas)."
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit(); print(f"Agregados {cantidad} pollos.")
            return jsonify({"success": True, "message": f"{cantidad} pollos agregados."})
    except psycopg2.Error as e: print(f"Error DB add_pollos: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al actualizar (APo2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/add/presas_total', methods=['POST'])
def add_presas_total():
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (APrT1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
             cur.execute("INSERT INTO inventory_info (key, value_int) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value_int = inventory_info.value_int + EXCLUDED.value_int;", (PRESAS_KEY, cantidad))
             log_msg = f"ENTRADA: {cantidad} presas (generales) agregadas."
             if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
             conn.commit(); print(f"Agregadas {cantidad} presas generales.")
             return jsonify({"success": True, "message": f"{cantidad} presas agregadas."})
    except psycopg2.Error as e: print(f"Error DB add_presas_total: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al actualizar (APrT2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/add/producto', methods=['POST'])
def add_producto():
    req_data = request.get_json(); nombre = req_data.get('name', '').strip().capitalize(); cantidad = req_data.get('quantity'); precio_str = req_data.get('price')
    if not nombre or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Nombre o cantidad inválidos."}), 400
    precio = Decimal('0.00')
    if precio_str is not None:
        try:
            precio_decimal = Decimal(str(precio_str));
            if precio_decimal >= 0: precio = precio_decimal.quantize(Decimal("0.01"))
            else: return jsonify({"success": False, "message": "Precio negativo."}), 400
        except InvalidOperation: return jsonify({"success": False, "message": "Formato de precio inválido."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (APd1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(""" INSERT INTO inventory_productos (nombre_producto, cantidad, precio) VALUES (%s, %s, %s) ON CONFLICT (nombre_producto) DO UPDATE SET cantidad = inventory_productos.cantidad + EXCLUDED.cantidad, precio = EXCLUDED.precio RETURNING cantidad; """, (nombre, cantidad, precio))
            result = cur.fetchone(); stock_actual = result['cantidad'] if result else 'N/A'
            log_msg = f"ENTRADA PRODUCTO: {cantidad} {nombre} (Precio: {precio}, Stock: {stock_actual})."
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit(); print(f"Producto: {cantidad} x {nombre} @ {precio}")
            return jsonify({"success": True, "message": f"{cantidad} '{nombre}' agregados/actualizados."})
    except psycopg2.Error as e: print(f"Error DB add_producto: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al actualizar (APd2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/sell', methods=['POST'])
def sell_cart():
    req_data = request.get_json(); cart = req_data.get('cart')
    if not isinstance(cart, list) or not cart: return jsonify({"success": False, "message": "Carrito inválido."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (S1)."}), 500
    total_venta = Decimal('0.00'); items_para_db = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT value FROM definitions WHERE key = 'combos'")
            combos_def_json = cur.fetchone()['value'] if cur.rowcount > 0 else {}
            cur.execute("SELECT key, value_int, value_numeric FROM inventory_info WHERE key IN (%s, %s) FOR UPDATE", (PRESAS_KEY, PRESA_PRICE_KEY))
            info_data = {row['key']: row['value_int'] if row['value_int'] is not None else Decimal(row['value_numeric']) for row in cur.fetchall()}
            current_presas_total = info_data.get(PRESAS_KEY, 0)
            presa_precio_default = info_data.get(PRESA_PRICE_KEY, DEFAULT_PRESA_PRICE)
            cur.execute("SELECT nombre_producto, cantidad, precio FROM inventory_productos FOR UPDATE")
            current_productos = {row['nombre_producto']: {"cantidad": row['cantidad'], "precio": Decimal(row['precio'])} for row in cur.fetchall()}
            requerimientos = {"presas_total": 0, "productos": {}}; items_faltantes = []; stock_suficiente = True
            for item in cart:
                tipo = item.get('tipo'); nombre = item.get('nombre'); cantidad = item.get('cantidad', 0); display_name = item.get('display', nombre); precio_unitario = Decimal('0.00')
                if cantidad <= 0: continue
                if tipo == 'combo':
                    if nombre not in combos_def_json: stock_suficiente = False; items_faltantes.append(f"Combo '{display_name}'?"); continue
                    combo_info = combos_def_json[nombre]
                    try: precio_unitario = Decimal(str(combo_info.get('precio', '0.00')))
                    except InvalidOperation: print(f"Adv: Precio inválido combo {nombre}")
                    requerimientos['presas_total'] += combo_info.get('presas_necesarias', 0) * cantidad
                    for p, cR in combo_info.get('productos', {}).items(): requerimientos['productos'][p] = requerimientos['productos'].get(p, 0) + cR * cantidad
                elif tipo == 'presa':
                    precio_unitario = presa_precio_default
                    requerimientos['presas_total'] += cantidad
                elif tipo == 'producto':
                    if nombre not in current_productos: stock_suficiente = False; items_faltantes.append(f"Prod '{display_name}'?"); continue
                    precio_unitario = current_productos[nombre]['precio']
                    requerimientos['productos'][nombre] = requerimientos['productos'].get(nombre, 0) + cantidad
                else: stock_suficiente = False; items_faltantes.append(f"Tipo? '{display_name}'")
                total_venta += precio_unitario * cantidad
                items_para_db.append({"type": tipo, "name": nombre, "display": display_name, "quantity": cantidad, "price": precio_unitario})
            if current_presas_total < requerimientos['presas_total']:
                stock_suficiente = False; items_faltantes.append(f"Presas({requerimientos['presas_total']}/{current_presas_total})")
            for p, cR in requerimientos['productos'].items():
                 if current_productos.get(p, {}).get('cantidad', 0) < cR: stock_suficiente = False; items_faltantes.append(f"{p}({cR}/{current_productos.get(p, {}).get('cantidad', 0)})")
            if not stock_suficiente: print(f"Venta fallida stock: {items_faltantes}"); conn.rollback(); return jsonify({"success": False, "message": f"Stock insuficiente: {', '.join(items_faltantes)}"}), 400
            print("Stock OK. Procesando venta en DB...")
            cur.execute("INSERT INTO sales (total_amount) VALUES (%s) RETURNING sale_id;", (total_venta,))
            sale_id = cur.fetchone()['sale_id']; print(f"Venta registrada ID: {sale_id}, Total: {total_venta}")
            items_sql_data = [(sale_id, i['type'], i['name'], i['display'], i['quantity'], i['price']) for i in items_para_db]
            cur.executemany("INSERT INTO sale_items (sale_id, item_type, item_name, display_name, quantity, price_per_item) VALUES (%s, %s, %s, %s, %s, %s)", items_sql_data)
            print(f"Items de la venta {sale_id} registrados.")
            print("Descontando inventario...")
            if requerimientos['presas_total'] > 0:
                cur.execute("UPDATE inventory_info SET value_int = value_int - %s WHERE key = %s AND value_int >= %s", (requerimientos['presas_total'], PRESAS_KEY, requerimientos['presas_total']))
                if cur.rowcount == 0: raise psycopg2.Error("Fallo al descontar presas (stock insuficiente concurrente?)")
            for p, cR in requerimientos['productos'].items():
                cur.execute("UPDATE inventory_productos SET cantidad = cantidad - %s WHERE nombre_producto = %s AND cantidad >= %s", (cR, p, cR))
                if cur.rowcount == 0: raise psycopg2.Error(f"Fallo al descontar producto {p} (stock insuficiente concurrente?)")
            print("Inventario descontado.")
            resumen_display = ', '.join([f"{item['cantidad']}x{item.get('display', item['nombre'])}" for item in cart]); total_venta_str = f"{total_venta:.2f}"
            log_msg = f"VENTA CARRITO (ID:{sale_id}, {len(cart)} items): {resumen_display}. Total: ${total_venta_str}"
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial simple")
            conn.commit(); print(f"Venta {sale_id} confirmada.")
            return jsonify({"success": True, "message": "Venta procesada!"})
    except psycopg2.Error as e: print(f"Error DB sell_cart: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error interno al vender (S2)."}), 500
    except InvalidOperation as e: print(f"Error de precio en venta: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error en formato de precio."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/remove/pollos', methods=['POST'])
def remove_pollos():
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (RPo1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT value FROM definitions WHERE key = %s", (PRESAS_PER_POLLO_KEY,))
            result = cur.fetchone(); presas_pp = result['value'] if result else 8
            presas_a_quitar = cantidad * presas_pp
            cur.execute("SELECT value_int FROM inventory_info WHERE key = %s FOR UPDATE", (PRESAS_KEY,))
            result = cur.fetchone(); current_presas_total = result['value_int'] if result else 0
            if current_presas_total < presas_a_quitar:
                msg = f"Presas insuficientes ({current_presas_total}) para eliminar {cantidad} pollos ({presas_a_quitar} requeridas)."
                print(msg); conn.rollback(); return jsonify({"success": False, "message": msg}), 400
            cur.execute("UPDATE inventory_info SET value_int = value_int - %s WHERE key = 'pollosEnteros' AND value_int >= %s", (cantidad, cantidad))
            cur.execute("UPDATE inventory_info SET value_int = value_int - %s WHERE key = %s AND value_int >= %s", (presas_a_quitar, PRESAS_KEY, presas_a_quitar))
            if cur.rowcount == 0: raise psycopg2.Error("Fallo al descontar presas (stock insuficiente concurrente?)")
            log_msg = f"ELIMINACIÓN: {cantidad} pollos enteros (merma, {presas_a_quitar} presas)."
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit(); print(f"Eliminados {cantidad} pollos (merma).")
            return jsonify({"success": True, "message": f"{cantidad} pollos eliminados." })
    except psycopg2.Error as e: print(f"Error DB remove_pollos: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al eliminar pollos (RPo2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/remove/presas_total', methods=['POST'])
def remove_presas_total():
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (RPrT1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("UPDATE inventory_info SET value_int = value_int - %s WHERE key = %s AND value_int >= %s", (cantidad, PRESAS_KEY, cantidad))
            if cur.rowcount == 0:
                 cur.execute("SELECT value_int FROM inventory_info WHERE key = %s", (PRESAS_KEY,))
                 stock_actual = cur.fetchone(); stock_disp = stock_actual['value_int'] if stock_actual else 0
                 msg = f"Stock insuficiente de presas (Disp: {stock_disp})"; conn.rollback(); return jsonify({"success": False, "message": msg}), 400
            log_msg = f"ELIMINACIÓN: {cantidad} presas generales (merma)."
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit(); print(f"Eliminadas {cantidad} presas generales (merma).")
            return jsonify({"success": True, "message": f"{cantidad} presas eliminadas." })
    except psycopg2.Error as e: print(f"Error DB remove_presas_total: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al eliminar presas (RPrT2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/remove/producto', methods=['POST'])
def remove_producto():
    req_data = request.get_json(); nombre = req_data.get('name', '').strip().capitalize(); cantidad = req_data.get('quantity')
    if not nombre or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (RPd1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("UPDATE inventory_productos SET cantidad = cantidad - %s WHERE nombre_producto = %s AND cantidad >= %s RETURNING cantidad", (cantidad, nombre, cantidad))
            result = cur.fetchone()
            if result is None:
                cur.execute("SELECT cantidad FROM inventory_productos WHERE nombre_producto = %s", (nombre,))
                stock_actual = cur.fetchone(); stock_disp = stock_actual['cantidad'] if stock_actual else 0
                msg = f"Stock insuf. o producto '{nombre}' no existe (Disp: {stock_disp})"; conn.rollback(); return jsonify({"success": False, "message": msg}), 400
            stock_restante = result['cantidad']
            log_msg = f"ELIMINACIÓN PRODUCTO: {cantidad} {nombre} (merma). Stock: {stock_restante}."
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit(); print(f"Eliminado producto: {cantidad} x {nombre} (merma).")
            return jsonify({"success": True, "message": f"{cantidad} '{nombre}' eliminados." })
    except psycopg2.Error as e: print(f"Error DB remove_producto: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al eliminar producto (RPd2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/reports/sales', methods=['GET'])
def get_sales_report():
    start_date_str = request.args.get('start_date'); end_date_str = request.args.get('end_date')
    start_date = None; end_date = None
    if start_date_str:
        try: start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except ValueError: return jsonify({"success": False, "message": "Formato fecha inicial inválido."}), 400
    if end_date_str:
        try: end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date(); end_date = datetime.datetime.combine(end_date, datetime.time.max)
        except ValueError: return jsonify({"success": False, "message": "Formato fecha final inválido."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (R1)."}), 500
    sales_list = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            sql = """ SELECT s.sale_id, s.timestamp, s.total_amount, si.item_type, si.display_name, si.quantity, si.price_per_item FROM sales s JOIN sale_items si ON s.sale_id = si.sale_id """
            params = []; conditions = []
            if start_date: conditions.append("s.timestamp >= %s"); params.append(start_date)
            if end_date: conditions.append("s.timestamp <= %s"); params.append(end_date)
            if conditions: sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY s.timestamp DESC, s.sale_id DESC, si.item_id ASC;"
            cur.execute(sql, tuple(params)); results = cur.fetchall()
            sales_dict = {}
            for row in results:
                sale_id = row['sale_id']
                if sale_id not in sales_dict: sales_dict[sale_id] = { "sale_id": sale_id, "timestamp": row['timestamp'].isoformat(), "total_amount": float(row['total_amount']), "items": [] }
                sales_dict[sale_id]['items'].append({ "type": row['item_type'], "name": row['display_name'], "quantity": row['quantity'], "price": float(row['price_per_item']) })
            sales_list = list(sales_dict.values())
        return jsonify({"success": True, "sales": sales_list})
    except psycopg2.Error as e: print(f"Error DB get_sales_report: {e}"); return jsonify({"success": False, "message": "Error interno (R2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/update/price', methods=['POST'])
def update_price():
    req_data = request.get_json(); item_type = req_data.get('item_type'); item_name = req_data.get('item_name'); new_price_str = req_data.get('new_price')
    if not item_type or new_price_str is None or (item_type != 'presa' and not item_name): return jsonify({"success": False, "message": "Faltan datos."}), 400
    if item_type not in ['producto', 'combo', 'presa']: return jsonify({"success": False, "message": "Tipo inválido."}), 400
    try:
        new_price = Decimal(str(new_price_str))
        if new_price < 0: return jsonify({"success": False, "message": "Precio negativo."}), 400
        new_price = new_price.quantize(Decimal("0.01"))
    except InvalidOperation: return jsonify({"success": False, "message": "Formato precio inválido."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (UP1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            log_msg = ""; rowcount = -1
            if item_type == 'producto':
                cur.execute("UPDATE inventory_productos SET precio = %s WHERE nombre_producto = %s", (new_price, item_name))
                rowcount = cur.rowcount
                if rowcount > 0: log_msg = f"PRECIO ACTUALIZADO: Producto '{item_name}' a ${new_price}."
            elif item_type == 'presa': # Actualizar el precio default de presas
                cur.execute("INSERT INTO inventory_info (key, value_numeric) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value_numeric = EXCLUDED.value_numeric;", (PRESA_PRICE_KEY, new_price))
                rowcount = cur.rowcount # Devuelve 0 o 1
                log_msg = f"PRECIO ACTUALIZADO: Precio de Presa General a ${new_price}."
            elif item_type == 'combo':
                cur.execute("SELECT value FROM definitions WHERE key = 'combos' FOR UPDATE")
                result = cur.fetchone()
                if not result: conn.rollback(); return jsonify({"success": False, "message": "Definición combos no encontrada."}), 404
                combos_dict = result['value']
                if item_name not in combos_dict: conn.rollback(); return jsonify({"success": False, "message": f"Combo '{item_name}' no encontrado."}), 404
                combos_dict[item_name]['precio'] = str(new_price)
                cur.execute("UPDATE definitions SET value = %s WHERE key = 'combos'", (json.dumps(combos_dict),))
                rowcount = cur.rowcount
                log_msg = f"PRECIO ACTUALIZADO: Combo '{item_name}' a ${new_price}."

            if rowcount == 0 and item_type == 'producto': conn.rollback(); return jsonify({"success": False, "message": f"Item '{item_name}' no encontrado."}), 404
            if not log_msg: conn.rollback(); return jsonify({"success": False, "message": f"Error al actualizar precio para {item_name}."}), 500

            print(log_msg)
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit()
            return jsonify({"success": True, "message": log_msg})
    except psycopg2.Error as e: print(f"Error DB update_price: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error interno (UP2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/add/custom_combo', methods=['POST'])
def add_custom_combo():
    req_data = request.get_json(); combo_name = req_data.get('name', '').strip(); combo_price_str = req_data.get('price'); items = req_data.get('items')
    if not combo_name: return jsonify({"success": False, "message": "Nombre requerido."}), 400
    if not isinstance(items, list) or not items: return jsonify({"success": False, "message": "Items requeridos."}), 400
    try:
        combo_price = Decimal(str(combo_price_str));
        if combo_price < 0: return jsonify({"success": False, "message": "Precio inválido."}), 400
        combo_price = combo_price.quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError): return jsonify({"success": False, "message": "Formato precio inválido."}), 400
    normalized_name = re.sub(r'\s+', '_', combo_name.lower()); normalized_name = re.sub(r'[^\w-]', '', normalized_name); combo_key = f"custom_{normalized_name}"
    if not combo_key.replace('custom_', ''): return jsonify({"success": False, "message": "Nombre inválido."}), 400
    new_combo_data = {"presas_necesarias": 0, "productos": {}, "precio": str(combo_price)}; valid_item_types = ['presa', 'producto']
    conn_check = get_db_connection();
    if not conn_check: return jsonify({"success": False, "message": "Error DB (CC_Check1)."}), 500
    try:
        with conn_check.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur_check:
            cur_check.execute("SELECT nombre_producto FROM inventory_productos"); valid_productos = {row['nombre_producto'] for row in cur_check.fetchall()}
    except psycopg2.Error as e: print(f"Error DB validando items: {e}"); return jsonify({"success": False, "message": "Error interno (CC_Check2)."}), 500
    finally:
        if conn_check: conn_check.close()
    for item in items:
        item_type = item.get('type', '').lower(); item_name = item.get('name'); item_qty = item.get('quantity')
        if item_type not in valid_item_types or not item_name or not isinstance(item_qty, int) or item_qty <= 0: return jsonify({"success": False, "message": f"Item inválido: {item}"}), 400
        if item_type == 'presa':
            new_combo_data['presas_necesarias'] += item_qty
        elif item_type == 'producto':
            item_name_cap = item_name.capitalize()
            if item_name_cap not in valid_productos: return jsonify({"success": False, "message": f"Producto '{item_name_cap}' no válido."}), 400
            new_combo_data['productos'][item_name_cap] = new_combo_data['productos'].get(item_name_cap, 0) + item_qty
    if new_combo_data['presas_necesarias'] == 0 and not new_combo_data['productos']: return jsonify({"success": False, "message": "Combo debe tener items."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (CC1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT value FROM definitions WHERE key = 'combos' FOR UPDATE")
            result = cur.fetchone(); combos_dict = result['value'] if result else {}
            if combo_key in combos_dict: conn.rollback(); return jsonify({"success": False, "message": f"Combo similar ya existe ('{combo_key}')."}), 400
            combos_dict[combo_key] = new_combo_data
            cur.execute("INSERT INTO definitions (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;", ('combos', json.dumps(combos_dict)))
            log_msg = f"COMBO PERSONALIZADO AÑADIDO: '{combo_name}' (ID: {combo_key}, Precio: ${combo_price})."
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit(); print(log_msg)
            return jsonify({"success": True, "message": f"Combo '{combo_name}' añadido."})
    except psycopg2.Error as e: print(f"Error DB add_custom_combo: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error interno (CC2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/remove/custom_combo', methods=['POST'])
def remove_custom_combo():
    req_data = request.get_json(); combo_key = req_data.get('combo_key')
    if not combo_key or not combo_key.startswith('custom_'): return jsonify({"success": False, "message": "Clave inválida o no es personalizado."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (RC1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT value FROM definitions WHERE key = 'combos' FOR UPDATE")
            result = cur.fetchone()
            if not result: conn.rollback(); return jsonify({"success": False, "message": "Definición combos no encontrada."}), 404
            combos_dict = result['value']
            if combo_key not in combos_dict: conn.rollback(); return jsonify({"success": False, "message": f"Combo '{combo_key}' no encontrado."}), 404
            combo_name_display = combo_key.replace('custom_', '').replace('_', ' ').capitalize()
            del combos_dict[combo_key]; print(f"Combo '{combo_key}' eliminado del diccionario.")
            cur.execute("UPDATE definitions SET value = %s WHERE key = 'combos'", (json.dumps(combos_dict),))
            log_msg = f"COMBO PERSONALIZADO ELIMINADO: '{combo_name_display}' (ID: {combo_key})."
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit(); print(log_msg)
            return jsonify({"success": True, "message": f"Combo '{combo_name_display}' eliminado."})
    except psycopg2.Error as e: print(f"Error DB remove_custom_combo: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error interno (RC2)."}), 500
    finally:
        if conn: conn.close()

# --- Ejecutar la Aplicación ---
if __name__ == '__main__':
    print("Iniciando servidor Flask para DESARROLLO LOCAL...")
    app.run(host='0.0.0.0', port=5000, debug=True)