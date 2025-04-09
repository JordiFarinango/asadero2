# app.py - Backend con Flask, PostgreSQL y Combos Personalizados

import os
import json
import datetime
import psycopg2
import psycopg2.extras
import re # Para normalizar nombres de combos
from decimal import Decimal, InvalidOperation
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# --- Configuración Inicial ---
app = Flask(__name__)
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print("¡ERROR FATAL! Variable de entorno DATABASE_URL no encontrada.")
CORS(app, resources={r"/*": {"origins": "*"}}) # Permitir todo por ahora

# --- Conexión a Base de Datos ---
def get_db_connection():
    """Establece conexión con la base de datos PostgreSQL."""
    if not DATABASE_URL: print("Intento de conexión DB fallido: DATABASE_URL no configurada."); return None
    try: conn = psycopg2.connect(DATABASE_URL); return conn
    except psycopg2.OperationalError as e: print(f"Error conectando a la base de datos: {e}"); return None

# --- Inicialización de la Base de Datos ---
def init_db():
    """Crea/Actualiza las tablas necesarias si no existen."""
    print("Intentando inicializar/actualizar DB...")
    conn = get_db_connection()
    if not conn: print("No se pudo conectar a la DB para inicializar."); return

    try:
        with conn.cursor() as cur:
            # Verificar/Crear todas las tablas (users, inventory_*, history, definitions, sales, sale_items)
            print("Verificando tabla 'users'...")
            cur.execute("CREATE TABLE IF NOT EXISTS users (username VARCHAR(80) PRIMARY KEY, password_hash VARCHAR(255) NOT NULL, role VARCHAR(50) NOT NULL);")
            print("Verificando tabla 'inventory_presas'...")
            cur.execute("CREATE TABLE IF NOT EXISTS inventory_presas (nombre_presa VARCHAR(80) PRIMARY KEY, cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0), precio NUMERIC(10, 2) NOT NULL DEFAULT 1.00 CHECK (precio >= 0.00));")
            cur.execute("ALTER TABLE inventory_presas ADD COLUMN IF NOT EXISTS precio NUMERIC(10, 2) NOT NULL DEFAULT 1.00 CHECK (precio >= 0.00);")
            print("Verificando tabla 'inventory_productos'...")
            cur.execute("CREATE TABLE IF NOT EXISTS inventory_productos (nombre_producto VARCHAR(100) PRIMARY KEY, cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0), precio NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (precio >= 0.00));")
            cur.execute("ALTER TABLE inventory_productos ADD COLUMN IF NOT EXISTS precio NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (precio >= 0.00);")
            print("Verificando tabla 'inventory_info'...")
            cur.execute("CREATE TABLE IF NOT EXISTS inventory_info ( key VARCHAR(50) PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0 );")
            print("Verificando tabla 'history'...")
            cur.execute("CREATE TABLE IF NOT EXISTS history ( id SERIAL PRIMARY KEY, timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, message TEXT NOT NULL );")
            print("Verificando tabla 'definitions'...")
            cur.execute("CREATE TABLE IF NOT EXISTS definitions ( key VARCHAR(50) PRIMARY KEY, value JSONB NOT NULL );")
            print("Verificando tabla 'sales'...")
            cur.execute("CREATE TABLE IF NOT EXISTS sales (sale_id SERIAL PRIMARY KEY, timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, total_amount NUMERIC(10, 2) NOT NULL CHECK (total_amount >= 0.00));")
            print("Verificando tabla 'sale_items'...")
            cur.execute("CREATE TABLE IF NOT EXISTS sale_items (item_id SERIAL PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(sale_id) ON DELETE CASCADE, item_type VARCHAR(50) NOT NULL, item_name VARCHAR(100) NOT NULL, display_name VARCHAR(150), quantity INTEGER NOT NULL CHECK (quantity > 0), price_per_item NUMERIC(10, 2) NOT NULL CHECK (price_per_item >= 0.00));")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sale_items_sale_id ON sale_items (sale_id);")

            # --- Insertar/Actualizar datos iniciales ---
            # Usuarios
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING;", ('admin', generate_password_hash("admin123"), 'admin'))
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING;", ('venta', generate_password_hash("venta123"), 'vendedor'))
            # Presas Base
            presas_base = ["pechuga", "muslo", "ala", "pierna"]
            for p in presas_base: cur.execute("INSERT INTO inventory_presas (nombre_presa, cantidad) VALUES (%s, 0) ON CONFLICT (nombre_presa) DO NOTHING;", (p,))
            # Productos Base
            initial_productos = [('Papas', 10, Decimal('1.50')), ('Gaseosa', 15, Decimal('0.75')), ('Ají', 5, Decimal('0.50'))]
            for nombre, cant, precio in initial_productos: cur.execute("INSERT INTO inventory_productos (nombre_producto, cantidad, precio) VALUES (%s, %s, %s) ON CONFLICT (nombre_producto) DO UPDATE SET precio = EXCLUDED.precio;", (nombre, cant, precio)) # Solo actualiza precio si ya existe
            # Info Base
            cur.execute("INSERT INTO inventory_info (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;", ('pollosEnteros', 0))
            # Definiciones Base
            initial_combos = { "combo_1_8_pechuga": { "presas": { "pechuga": 1 }, "productos": {}, "precio": "2.00" }, "combo_1_8_muslo":   { "presas": { "muslo": 1 },   "productos": {}, "precio": "2.00" }, "combo_1_8_ala":     { "presas": { "ala": 1 },     "productos": {}, "precio": "1.75" }, "combo_1_8_pierna":  { "presas": { "pierna": 1 },  "productos": {}, "precio": "1.75" }, "combo_1_4_pechuga_ala": { "presas": { "pechuga": 1, "ala": 1 }, "productos": {}, "precio": "3.50" }, "combo_1_4_muslo_pierna":{ "presas": { "muslo": 1, "pierna": 1 }, "productos": {}, "precio": "3.50" }, "combo_1_2": { "presas": { "pechuga": 1, "ala": 1, "muslo": 1, "pierna": 1 }, "productos": {}, "precio": "6.50" }, "combo_entero": { "presas": { "pechuga": 2, "ala": 2, "muslo": 2, "pierna": 2 }, "productos": {}, "precio": "12.00" } }
            initial_presas_por_pollo = { "pechuga": 2, "muslo": 2, "ala": 2, "pierna": 2 }
            cur.execute("INSERT INTO definitions (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;", ('combos', json.dumps(initial_combos))) # No sobreescribir combos existentes
            cur.execute("INSERT INTO definitions (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;", ('presasPorPollo', json.dumps(initial_presas_por_pollo)))

            conn.commit()
            print("Base de datos inicializada/actualizada.")
    except psycopg2.Error as e: print(f"Error durante inicialización/actualización de DB: {e}"); conn.rollback()
    finally:
        if conn: conn.close()

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
        if user_info and check_password_hash(user_info['password_hash'], password_attempt):
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
            cur.execute("SELECT nombre_presa, cantidad, precio FROM inventory_presas")
            presas = {row['nombre_presa']: {"cantidad": row['cantidad'], "precio": float(row['precio'])} for row in cur.fetchall()}
            cur.execute("SELECT nombre_producto, cantidad, precio FROM inventory_productos")
            productos = {row['nombre_producto']: {"cantidad": row['cantidad'], "precio": float(row['precio'])} for row in cur.fetchall()}
            cur.execute("SELECT value FROM inventory_info WHERE key = 'pollosEnteros'")
            result = cur.fetchone(); pollos_enteros = result['value'] if result else 0
            cur.execute("SELECT key, value FROM definitions")
            definitions = {row['key']: row['value'] for row in cur.fetchall()}
            combos_con_precio_float = {}
            for key, combo_data in definitions.get('combos', {}).items():
                try: combos_con_precio_float[key] = { "presas": combo_data.get("presas", {}), "productos": combo_data.get("productos", {}), "precio": float(combo_data.get("precio", "0.00")) }
                except (ValueError, TypeError): combos_con_precio_float[key] = { "presas": combo_data.get("presas", {}), "productos": combo_data.get("productos", {}), "precio": 0.00 }
            inventory_data = { "inventory": {"pollosEnteros": pollos_enteros, "presas": presas, "productos": productos}, "combos": combos_con_precio_float, "presasPorPollo": definitions.get('presasPorPollo', {}) }
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

# --- RUTAS AGREGAR ---
@app.route('/api/add/pollos', methods=['POST'])
def add_pollos():
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (APo1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT value FROM definitions WHERE key = 'presasPorPollo'")
            result = cur.fetchone(); presas_por_pollo = result['value'] if result else {}
            cur.execute("INSERT INTO inventory_info (key, value) VALUES ('pollosEnteros', %s) ON CONFLICT (key) DO UPDATE SET value = inventory_info.value + EXCLUDED.value;", (cantidad,))
            for p, c in presas_por_pollo.items(): cur.execute("INSERT INTO inventory_presas (nombre_presa, cantidad) VALUES (%s, %s) ON CONFLICT (nombre_presa) DO UPDATE SET cantidad = inventory_presas.cantidad + EXCLUDED.cantidad;", (p, cantidad * c))
            log_msg = f"ENTRADA: {cantidad} pollos enteros agregados."
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit(); print(f"Agregados {cantidad} pollos.")
            return jsonify({"success": True, "message": f"{cantidad} pollos agregados."})
    except psycopg2.Error as e: print(f"Error DB add_pollos: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al actualizar (APo2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/add/presas', methods=['POST'])
def add_presas():
    req_data = request.get_json(); tipo = req_data.get('type', '').lower(); cantidad = req_data.get('quantity')
    if not tipo or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (APr1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
             cur.execute("SELECT value FROM definitions WHERE key = 'presasPorPollo'")
             result = cur.fetchone(); presas_validas = result['value'].keys() if result else []
             if tipo not in presas_validas: return jsonify({"success": False, "message": f"Tipo '{tipo}' inválido."}), 400
             cur.execute("INSERT INTO inventory_presas (nombre_presa, cantidad) VALUES (%s, %s) ON CONFLICT (nombre_presa) DO UPDATE SET cantidad = inventory_presas.cantidad + EXCLUDED.cantidad;", (tipo, cantidad))
             log_msg = f"ENTRADA: {cantidad} {tipo}(s) individuales agregadas."
             if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
             conn.commit(); print(f"Agregadas {cantidad} {tipo}(s).")
             return jsonify({"success": True, "message": f"{cantidad} {tipo}(s) agregados."})
    except psycopg2.Error as e: print(f"Error DB add_presas: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al actualizar (APr2)."}), 500
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

# --- RUTA VENDER (Modificada para manejar productos en combos) ---
@app.route('/api/sell', methods=['POST'])
def sell_cart():
    req_data = request.get_json(); cart = req_data.get('cart')
    if not isinstance(cart, list) or not cart: return jsonify({"success": False, "message": "Carrito inválido."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (S1)."}), 500
    total_venta = Decimal('0.00'); items_para_db = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Bloquear tablas relevantes para la transacción
            cur.execute("SELECT value FROM definitions WHERE key = 'combos' FOR UPDATE")
            combos_def_json = cur.fetchone()['value'] if cur.rowcount > 0 else {}
            cur.execute("SELECT nombre_presa, cantidad, precio FROM inventory_presas FOR UPDATE")
            current_presas = {row['nombre_presa']: {"cantidad": row['cantidad'], "precio": Decimal(row['precio'])} for row in cur.fetchall()}
            cur.execute("SELECT nombre_producto, cantidad, precio FROM inventory_productos FOR UPDATE")
            current_productos = {row['nombre_producto']: {"cantidad": row['cantidad'], "precio": Decimal(row['precio'])} for row in cur.fetchall()}

            requerimientos = {"presas": {}, "productos": {}}; items_faltantes = []; stock_suficiente = True
            # Calcular requerimientos y total
            for item in cart:
                tipo = item.get('tipo'); nombre = item.get('nombre'); cantidad = item.get('cantidad', 0); display_name = item.get('display', nombre); precio_unitario = Decimal('0.00')
                if cantidad <= 0: continue
                if tipo == 'combo':
                    if nombre not in combos_def_json: stock_suficiente = False; items_faltantes.append(f"Combo '{display_name}'?"); continue
                    combo_info = combos_def_json[nombre]
                    try: precio_unitario = Decimal(str(combo_info.get('precio', '0.00')))
                    except InvalidOperation: print(f"Adv: Precio inválido combo {nombre}")
                    for p, cR in combo_info.get('presas', {}).items(): requerimientos['presas'][p] = requerimientos['presas'].get(p, 0) + cR * cantidad
                    for p, cR in combo_info.get('productos', {}).items(): requerimientos['productos'][p] = requerimientos['productos'].get(p, 0) + cR * cantidad # Considerar productos
                elif tipo == 'presa':
                    if nombre not in current_presas: stock_suficiente = False; items_faltantes.append(f"Presa '{display_name}'?"); continue
                    precio_unitario = current_presas[nombre]['precio']
                    requerimientos['presas'][nombre] = requerimientos['presas'].get(nombre, 0) + cantidad
                elif tipo == 'producto':
                    if nombre not in current_productos: stock_suficiente = False; items_faltantes.append(f"Prod '{display_name}'?"); continue
                    precio_unitario = current_productos[nombre]['precio']
                    requerimientos['productos'][nombre] = requerimientos['productos'].get(nombre, 0) + cantidad
                else: stock_suficiente = False; items_faltantes.append(f"Tipo? '{display_name}'")
                total_venta += precio_unitario * cantidad
                items_para_db.append({"type": tipo, "name": nombre, "display": display_name, "quantity": cantidad, "price": precio_unitario})

            # Comprobar stock
            for p, cR in requerimientos['presas'].items():
                if current_presas.get(p, {}).get('cantidad', 0) < cR: stock_suficiente = False; items_faltantes.append(f"{p}({cR}/{current_presas.get(p, {}).get('cantidad', 0)})")
            for p, cR in requerimientos['productos'].items():
                 if current_productos.get(p, {}).get('cantidad', 0) < cR: stock_suficiente = False; items_faltantes.append(f"{p}({cR}/{current_productos.get(p, {}).get('cantidad', 0)})")

            if not stock_suficiente: print(f"Venta fallida stock: {items_faltantes}"); conn.rollback(); return jsonify({"success": False, "message": f"Stock insuficiente: {', '.join(items_faltantes)}"}), 400

            # Si hay stock, descontar e insertar venta/items
            cur.execute("INSERT INTO sales (total_amount) VALUES (%s) RETURNING sale_id;", (total_venta,))
            sale_id = cur.fetchone()['sale_id'];
            items_sql_data = [(sale_id, i['type'], i['name'], i['display'], i['quantity'], i['price']) for i in items_para_db]
            cur.executemany("INSERT INTO sale_items (sale_id, item_type, item_name, display_name, quantity, price_per_item) VALUES (%s, %s, %s, %s, %s, %s)", items_sql_data)
            for p, cR in requerimientos['presas'].items(): cur.execute("UPDATE inventory_presas SET cantidad = cantidad - %s WHERE nombre_presa = %s", (cR, p))
            for p, cR in requerimientos['productos'].items(): cur.execute("UPDATE inventory_productos SET cantidad = cantidad - %s WHERE nombre_producto = %s", (cR, p))
            resumen_display = ', '.join([f"{item['cantidad']}x{item.get('display', item['nombre'])}" for item in cart]); total_venta_str = f"{total_venta:.2f}"
            log_msg = f"VENTA CARRITO (ID:{sale_id}, {len(cart)} items): {resumen_display}. Total: ${total_venta_str}"
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial simple")
            conn.commit(); print(f"Venta {sale_id} confirmada.")
            return jsonify({"success": True, "message": "Venta procesada!"})
    except psycopg2.Error as e: print(f"Error DB sell_cart: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error interno al vender (S2)."}), 500
    except InvalidOperation as e: print(f"Error de precio en venta: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error en formato de precio."}), 500
    finally:
        if conn: conn.close()

# --- RUTAS ELIMINAR ---
@app.route('/api/remove/pollos', methods=['POST'])
def remove_pollos():
    # ... (igual que antes) ...
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (RPo1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT value FROM definitions WHERE key = 'presasPorPollo'")
            presas_por_pollo = cur.fetchone()['value'] if cur.rowcount > 0 else {}
            cur.execute("SELECT nombre_presa, cantidad FROM inventory_presas FOR UPDATE")
            current_presas = {row['nombre_presa']: row['cantidad'] for row in cur.fetchall()}
            presas_necesarias = {}; stock_presas_suficiente = True
            for p, cPP in presas_por_pollo.items():
                req = cantidad * cPP
                if current_presas.get(p, 0) < req: stock_presas_suficiente = False; presas_necesarias[p] = f"Req:{req}/Disp:{current_presas.get(p, 0)}"
            if not stock_presas_suficiente: msg = f"Presas insuficientes: {presas_necesarias}"; print(msg); conn.rollback(); return jsonify({"success": False, "message": msg}), 400
            cur.execute("UPDATE inventory_info SET value = value - %s WHERE key = 'pollosEnteros' AND value >= %s", (cantidad, cantidad))
            for p, cPP in presas_por_pollo.items(): cur.execute("UPDATE inventory_presas SET cantidad = cantidad - %s WHERE nombre_presa = %s AND cantidad >= %s", (cantidad * cPP, p, cantidad * cPP))
            log_msg = f"ELIMINACIÓN: {cantidad} pollos enteros (merma)."
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit(); print(f"Eliminados {cantidad} pollos (merma).")
            return jsonify({"success": True, "message": f"{cantidad} pollos eliminados." })
    except psycopg2.Error as e: print(f"Error DB remove_pollos: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al eliminar pollos (RPo2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/remove/presas', methods=['POST'])
def remove_presas():
    # ... (igual que antes) ...
    req_data = request.get_json(); tipo = req_data.get('type', '').lower(); cantidad = req_data.get('quantity')
    if not tipo or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (RPr1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("UPDATE inventory_presas SET cantidad = cantidad - %s WHERE nombre_presa = %s AND cantidad >= %s", (cantidad, tipo, cantidad))
            if cur.rowcount == 0:
                 cur.execute("SELECT cantidad FROM inventory_presas WHERE nombre_presa = %s", (tipo,))
                 stock_actual = cur.fetchone(); stock_disp = stock_actual['cantidad'] if stock_actual else 0
                 msg = f"Stock insuf. o presa '{tipo}' no existe (Disp: {stock_disp})"; conn.rollback(); return jsonify({"success": False, "message": msg}), 400
            log_msg = f"ELIMINACIÓN: {cantidad} {tipo}(s) (merma)."
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit(); print(f"Eliminadas {cantidad} {tipo}(s) (merma).")
            return jsonify({"success": True, "message": f"{cantidad} {tipo}(s) eliminados." })
    except psycopg2.Error as e: print(f"Error DB remove_presas: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al eliminar presas (RPr2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/remove/producto', methods=['POST'])
def remove_producto():
    # ... (igual que antes) ...
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
    # ... (igual que antes) ...
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
    # ... (igual que antes) ...
    req_data = request.get_json(); item_type = req_data.get('item_type'); item_name = req_data.get('item_name'); new_price_str = req_data.get('new_price')
    if not item_type or not item_name or new_price_str is None: return jsonify({"success": False, "message": "Faltan datos."}), 400
    try:
        new_price = Decimal(str(new_price_str))
        if new_price < 0: return jsonify({"success": False, "message": "Precio negativo."}), 400
        new_price = new_price.quantize(Decimal("0.01"))
    except InvalidOperation: return jsonify({"success": False, "message": "Formato de precio inválido."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (UP1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            log_msg = ""; rowcount = 0; affected_items = 0
            if item_type == 'producto':
                cur.execute("UPDATE inventory_productos SET precio = %s WHERE nombre_producto = %s", (new_price, item_name))
                affected_items = cur.rowcount
                if affected_items > 0: log_msg = f"PRECIO ACTUALIZADO: Producto '{item_name}' a ${new_price}."
            elif item_type == 'presa':
                cur.execute("UPDATE inventory_presas SET precio = %s WHERE nombre_presa = %s", (new_price, item_name))
                affected_items = cur.rowcount
                if affected_items > 0: log_msg = f"PRECIO ACTUALIZADO: Presa '{item_name}' a ${new_price}."
            elif item_type == 'combo':
                cur.execute("SELECT value FROM definitions WHERE key = 'combos' FOR UPDATE")
                result = cur.fetchone()
                if not result: conn.rollback(); return jsonify({"success": False, "message": "Definición combos no encontrada."}), 404
                combos_dict = result['value']
                if item_name not in combos_dict: conn.rollback(); return jsonify({"success": False, "message": f"Combo '{item_name}' no encontrado."}), 404
                combos_dict[item_name]['precio'] = str(new_price)
                cur.execute("UPDATE definitions SET value = %s WHERE key = 'combos'", (json.dumps(combos_dict),))
                affected_items = cur.rowcount # UPDATE en JSONB puede no retornar filas afectadas de forma útil
                log_msg = f"PRECIO ACTUALIZADO: Combo '{item_name}' a ${new_price}." # Asumir éxito si no hay error
            else:
                conn.rollback(); return jsonify({"success": False, "message": "Tipo de item inválido."}), 400

            if affected_items == 0 and item_type != 'combo': # Para producto/presa, 0 filas afectadas significa no encontrado
                 conn.rollback(); return jsonify({"success": False, "message": f"Item '{item_name}' no encontrado."}), 404

            print(log_msg)
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit()
            return jsonify({"success": True, "message": log_msg})

    except psycopg2.Error as e: print(f"Error DB update_price: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error interno (UP2)."}), 500
    finally:
        if conn: conn.close()

# --- NUEVA RUTA PARA AÑADIR COMBOS PERSONALIZADOS ---
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

    # Normalizar nombre para clave interna
    normalized_name = re.sub(r'\s+', '_', combo_name.lower()); normalized_name = re.sub(r'[^\w-]', '', normalized_name); combo_key = f"custom_{normalized_name}"
    if not normalized_name: return jsonify({"success": False, "message": "Nombre inválido (solo letras, números, -, _)."}), 400

    new_combo_data = {"presas": {}, "productos": {}, "precio": str(combo_price)}; valid_item_types = ['presa', 'producto']
    conn_check = get_db_connection();
    if not conn_check: return jsonify({"success": False, "message": "Error DB (CC_Check1)."}), 500
    try: # Validar items y construir estructura
        with conn_check.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur_check:
            cur_check.execute("SELECT nombre_presa FROM inventory_presas"); valid_presas = {row['nombre_presa'] for row in cur_check.fetchall()}
            cur_check.execute("SELECT nombre_producto FROM inventory_productos"); valid_productos = {row['nombre_producto'] for row in cur_check.fetchall()}
        for item in items:
            item_type = item.get('type', '').lower(); item_name = item.get('name'); item_qty = item.get('quantity')
            if item_type not in valid_item_types or not item_name or not isinstance(item_qty, int) or item_qty <= 0: return jsonify({"success": False, "message": f"Item inválido: {item}"}), 400
            if item_type == 'presa':
                if item_name not in valid_presas: return jsonify({"success": False, "message": f"Presa '{item_name}' no válida."}), 400
                new_combo_data['presas'][item_name] = new_combo_data['presas'].get(item_name, 0) + item_qty # Sumar si se añade la misma presa varias veces
            elif item_type == 'producto':
                item_name_cap = item_name.capitalize() # Usar nombre capitalizado consistente
                if item_name_cap not in valid_productos: return jsonify({"success": False, "message": f"Producto '{item_name_cap}' no válido."}), 400
                new_combo_data['productos'][item_name_cap] = new_combo_data['productos'].get(item_name_cap, 0) + item_qty # Sumar si se añade el mismo producto
        if not new_combo_data['presas'] and not new_combo_data['productos']: return jsonify({"success": False, "message": "Combo debe tener items."}), 400
    except psycopg2.Error as e: print(f"Error DB validando items: {e}"); return jsonify({"success": False, "message": "Error interno (CC_Check2)."}), 500
    finally:
        if conn_check: conn_check.close()

    # --- Guardar en DB ---
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (CC1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT value FROM definitions WHERE key = 'combos' FOR UPDATE")
            result = cur.fetchone(); combos_dict = result['value'] if result else {}
            if combo_key in combos_dict: conn.rollback(); return jsonify({"success": False, "message": f"Combo similar ya existe ('{combo_key}'). Use otro nombre."}), 400
            combos_dict[combo_key] = new_combo_data
            cur.execute("INSERT INTO definitions (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;", ('combos', json.dumps(combos_dict)))
            log_msg = f"COMBO PERSONALIZADO AÑADIDO: '{combo_name}' (ID: {combo_key}, Precio: ${combo_price})."
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit(); print(log_msg)
            return jsonify({"success": True, "message": f"Combo '{combo_name}' añadido."})
    except psycopg2.Error as e: print(f"Error DB add_custom_combo: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error interno (CC2)."}), 500
    finally:
        if conn: conn.close()

# --- Ejecutar la Aplicación ---
if __name__ == '__main__':
    print("Iniciando servidor Flask para DESARROLLO LOCAL...")
    app.run(host='0.0.0.0', port=5000, debug=True)

