# app.py - Backend Completo Final (Corregido KeyError y con Rol Cocinero)

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
CORS(app, resources={r"/*": {"origins": "*"}}) # Considera restringir a tu URL de Netlify en producción

# --- Constantes ---
DEFAULT_PRESA_PRICE = Decimal("1.25") # Precio por defecto para una presa genérica
PRESAS_KEY = 'presas_total' # Clave usada en tabla inventory_info
PRESA_PRICE_KEY = 'presa_precio_default' # Clave usada en tabla inventory_info
PRESAS_PER_POLLO_KEY = 'presas_por_pollo_total' # Clave usada en tabla definitions
COMBOS_KEY = 'combos' # Clave usada en tabla definitions

# --- Conexión a Base de Datos ---
def get_db_connection():
    """Establece conexión con la base de datos PostgreSQL."""
    if not DATABASE_URL: print("Intento de conexión DB fallido: DATABASE_URL no configurada."); return None
    try: conn = psycopg2.connect(DATABASE_URL); return conn
    except psycopg2.OperationalError as e: print(f"Error conectando a la base de datos: {e}"); return None

# --- Inicialización de la Base de Datos ---
def init_db():
    """Crea/Actualiza las tablas necesarias si no existen."""
    print("Intentando inicializar/actualizar DB (con rol cocinero)...")
    conn = get_db_connection()
    if not conn: print("No se pudo conectar a la DB para inicializar."); return

    try:
        with conn.cursor() as cur:
            # Verificar/Crear todas las tablas
            print("Verificando tabla 'users'...")
            cur.execute("CREATE TABLE IF NOT EXISTS users (username VARCHAR(80) PRIMARY KEY, password_hash VARCHAR(255) NOT NULL, role VARCHAR(50) NOT NULL);")
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
            print("Verificando tabla 'pending_orders'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pending_orders (
                    order_id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- 'pending', 'completed'
                    items JSONB NOT NULL
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pending_orders_status ON pending_orders (status);")
            cur.execute("DROP TABLE IF EXISTS inventory_presas;") # Eliminar tabla obsoleta

            # --- Insertar/Actualizar datos iniciales ---
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING;", ('admin', generate_password_hash("admin123"), 'admin'))
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING;", ('venta', generate_password_hash("venta123"), 'vendedor'))
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING;", ('cocina', generate_password_hash("cocina123"), 'cocinero'))

            initial_productos = [('Papas', 0, Decimal('1.50')), ('Gaseosa', 0, Decimal('0.75')), ('Ají', 0, Decimal('0.50'))]
            for nombre, cant, precio in initial_productos:
                cur.execute("INSERT INTO inventory_productos (nombre_producto, cantidad, precio) VALUES (%s, %s, %s) ON CONFLICT (nombre_producto) DO NOTHING;", (nombre, cant, precio))

            cur.execute("INSERT INTO inventory_info (key, value_int) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;", ('pollosEnteros', 0))
            cur.execute("INSERT INTO inventory_info (key, value_int) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;", (PRESAS_KEY, 0))
            cur.execute("INSERT INTO inventory_info (key, value_numeric) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;", (PRESA_PRICE_KEY, DEFAULT_PRESA_PRICE))

            initial_presas_por_pollo_total = 8
            cur.execute("INSERT INTO definitions (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;",
                        (PRESAS_PER_POLLO_KEY, json.dumps(initial_presas_por_pollo_total)))
            initial_combos = {
                "combo_1_8": { "presas_necesarias": 1, "productos": {}, "precio": "2.00" },
                "combo_1_4": { "presas_necesarias": 2, "productos": {}, "precio": "3.50" },
                "combo_1_2": { "presas_necesarias": 4, "productos": {}, "precio": "6.50" },
                "combo_entero": { "presas_necesarias": initial_presas_por_pollo_total, "productos": {}, "precio": "12.00" }
            }
            cur.execute("INSERT INTO definitions (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;",
                        (COMBOS_KEY, json.dumps(initial_combos)))

            cur.execute("SELECT COUNT(*) FROM history;")
            if cur.fetchone()[0] == 0:
                 ts = datetime.datetime.now(datetime.timezone.utc)
                 cur.execute("INSERT INTO history (timestamp, message) VALUES (%s, %s)", (ts, "Sistema inicializado con DB (presas generales y órdenes)."))

            conn.commit()
            print("Base de datos inicializada/actualizada.")
    except psycopg2.Error as e: print(f"Error durante inicialización/actualización de DB: {e}"); conn.rollback()
    finally:
        if conn: conn.close()

# Llamar a init_db() al inicio
with app.app_context():
    init_db()

# --- Funciones Auxiliares ---
def add_history_db(message, conn):
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
                except (ValueError, TypeError, AttributeError): combos_con_precio_float[key] = { "presas_necesarias": 0, "productos": {}, "precio": 0.00 }
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
            history_list = [f"[{row[0].strftime('%Y-%m-%d %H:%M:%S') if row[0] else 'TS N/A'}] {row[1]}" for row in cur.fetchall()]
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
    req_data = request.get_json(); cart = req_data.get('cart'); informar_cocinero = req_data.get('informar_cocinero', False)
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
                tipo = item.get('tipo'); nombre = item.get('nombre'); cantidad = item.get('quantity', 0); display_name = item.get('display', nombre); precio_unitario = Decimal('0.00')
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
                items_para_db.append({"type": tipo, "name": nombre, "display": display_name, "quantity": cantidad, "price": float(precio_unitario)})
            if current_presas_total < requerimientos['presas_total']: stock_suficiente = False; items_faltantes.append(f"Presas({requerimientos['presas_total']}/{current_presas_total})")
            for p, cR in requerimientos['productos'].items():
                 if current_productos.get(p, {}).get('cantidad', 0) < cR: stock_suficiente = False; items_faltantes.append(f"{p}({cR}/{current_productos.get(p, {}).get('cantidad', 0)})")
            if not stock_suficiente: print(f"Venta fallida stock: {items_faltantes}"); conn.rollback(); return jsonify({"success": False, "message": f"Stock insuficiente: {', '.join(items_faltantes)}"}), 400
            cur.execute("INSERT INTO sales (total_amount) VALUES (%s) RETURNING sale_id;", (total_venta,))
            sale_id = cur.fetchone()['sale_id']; print(f"Venta registrada ID: {sale_id}, Total: {total_venta}")
            items_sql_data = [(sale_id, i['type'], i['name'], i['display'], i['quantity'], Decimal(str(i['price']))) for i in items_para_db]
            cur.executemany("INSERT INTO sale_items (sale_id, item_type, item_name, display_name, quantity, price_per_item) VALUES (%s, %s, %s, %s, %s, %s)", items_sql_data)
            if requerimientos['presas_total'] > 0:
                cur.execute("UPDATE inventory_info SET value_int = value_int - %s WHERE key = %s AND value_int >= %s", (requerimientos['presas_total'], PRESAS_KEY, requerimientos['presas_total']))
                if cur.rowcount == 0: raise psycopg2.Error("Fallo al descontar presas")
            for p, cR in requerimientos['productos'].items():
                cur.execute("UPDATE inventory_productos SET cantidad = cantidad - %s WHERE nombre_producto = %s AND cantidad >= %s", (cR, p, cR))
                if cur.rowcount == 0: raise psycopg2.Error(f"Fallo al descontar producto {p}")
            if informar_cocinero:
                items_json = json.dumps(items_para_db)
                cur.execute("INSERT INTO pending_orders (items) VALUES (%s);", (items_json,))
                print(f"Orden enviada a cocina para venta ID: {sale_id}")
            resumen_display = ', '.join([f"{item.get('quantity', '?')}x{item.get('display', item.get('name', '?'))}" for item in items_para_db]) # Usar .get()
            total_venta_str = f"{total_venta:.2f}"
            log_msg = f"VENTA CARRITO (ID:{sale_id}, {len(cart)} items): {resumen_display}. Total: ${total_venta_str}"
            if informar_cocinero: log_msg += " [Enviado a Cocina]"
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit(); print(f"Venta {sale_id} confirmada.")
            return jsonify({"success": True, "message": "Venta procesada!"})
    except psycopg2.Error as e: print(f"Error DB sell_cart: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error interno al vender (S2)."}), 500
    except InvalidOperation as e: print(f"Error de precio en venta: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error en formato de precio."}), 500
    except KeyError as e: print(f"KeyError en sell_cart: {e}"); conn.rollback(); return jsonify({"success": False, "message": f"Error interno procesando items (KeyError: {e})."}), 500
    finally:
        if conn: conn.close()

# --- RUTAS ELIMINAR ---
@app.route('/api/remove/pollos', methods=['POST'])
def remove_pollos():
    # ... (código igual que antes) ...
@app.route('/api/remove/presas_total', methods=['POST'])
def remove_presas_total():
    # ... (código igual que antes) ...
@app.route('/api/remove/producto', methods=['POST'])
def remove_producto():
    # ... (código igual que antes) ...

# --- RUTA REPORTE ---
@app.route('/api/reports/sales', methods=['GET'])
def get_sales_report():
    # ... (código igual que antes) ...

# --- RUTA ACTUALIZAR PRECIOS ---
@app.route('/api/update/price', methods=['POST'])
def update_price():
    # ... (código igual que antes) ...

# --- RUTAS COMBOS PERSONALIZADOS ---
@app.route('/api/add/custom_combo', methods=['POST'])
def add_custom_combo():
    # ... (código igual que antes) ...
@app.route('/api/remove/custom_combo', methods=['POST'])
def remove_custom_combo():
    # ... (código igual que antes) ...

# --- RUTAS PARA ÓRDENES DE COCINA ---
@app.route('/api/orders/pending', methods=['GET'])
def get_pending_orders():
    # ... (código igual que antes) ...
@app.route('/api/orders/complete/<int:order_id>', methods=['POST'])
def complete_order(order_id):
    # ... (código igual que antes) ...

# --- Ejecutar la Aplicación ---
if __name__ == '__main__':
    print("Iniciando servidor Flask para DESARROLLO LOCAL...")
    app.run(host='0.0.0.0', port=5000, debug=True)