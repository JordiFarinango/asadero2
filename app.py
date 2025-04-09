# app.py - Backend con Flask, PostgreSQL y Edición de Precios

import os
import json
import datetime
import psycopg2
import psycopg2.extras
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
    # ... (igual que antes) ...
    if not DATABASE_URL: print("Intento de conexión DB fallido: DATABASE_URL no configurada."); return None
    try: conn = psycopg2.connect(DATABASE_URL); return conn # No imprimir éxito cada vez
    except psycopg2.OperationalError as e: print(f"Error conectando a la base de datos: {e}"); return None

# --- Inicialización de la Base de Datos ---
def init_db():
    # ... (igual que antes, asegura que todas las tablas existan) ...
    print("Intentando inicializar/actualizar DB...")
    conn = get_db_connection()
    if not conn: print("No se pudo conectar a la DB para inicializar."); return
    try:
        with conn.cursor() as cur:
            # Verificar/Crear todas las tablas (users, inventory_*, history, definitions, sales, sale_items)
            cur.execute("CREATE TABLE IF NOT EXISTS users (...);") # Definición completa omitida por brevedad
            cur.execute("CREATE TABLE IF NOT EXISTS inventory_presas (...);")
            cur.execute("CREATE TABLE IF NOT EXISTS inventory_productos (...);")
            cur.execute("ALTER TABLE inventory_productos ADD COLUMN IF NOT EXISTS precio NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (precio >= 0.00);")
            cur.execute("CREATE TABLE IF NOT EXISTS inventory_info (...);")
            cur.execute("CREATE TABLE IF NOT EXISTS history (...);")
            cur.execute("CREATE TABLE IF NOT EXISTS definitions (...);")
            cur.execute("CREATE TABLE IF NOT EXISTS sales (...);")
            cur.execute("CREATE TABLE IF NOT EXISTS sale_items (...);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sale_items_sale_id ON sale_items (sale_id);")
            # ... (código para insertar datos iniciales si las tablas estaban vacías) ...
            conn.commit()
            print("Base de datos inicializada/actualizada.")
    except psycopg2.Error as e: print(f"Error durante inicialización/actualización de DB: {e}"); conn.rollback()
    finally:
        if conn: conn.close()

with app.app_context(): init_db()

# --- Funciones Auxiliares ---
def add_history_db(message, conn):
    # ... (igual que antes) ...
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO history (message) VALUES (%s)", (message,))
            cur.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY timestamp DESC LIMIT 100);")
        return True
    except psycopg2.Error as e: print(f"Error añadiendo historial a DB: {e}"); return False

# --- Rutas API (Login, Get Inventory, Get History, Add*, Sell, Remove* sin cambios funcionales) ---
@app.route('/')
def index(): return render_template('index.html')
@app.route('/login', methods=['POST'])
def login():
    # ... (código igual que antes) ...
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
    # ... (código igual que antes) ...
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (I1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT nombre_presa, cantidad FROM inventory_presas")
            presas = {row['nombre_presa']: row['cantidad'] for row in cur.fetchall()}
            cur.execute("SELECT nombre_producto, cantidad, precio FROM inventory_productos")
            productos = {row['nombre_producto']: {"cantidad": row['cantidad'], "precio": float(row['precio'])} for row in cur.fetchall()}
            cur.execute("SELECT value FROM inventory_info WHERE key = 'pollosEnteros'")
            result = cur.fetchone(); pollos_enteros = result['value'] if result else 0
            cur.execute("SELECT key, value FROM definitions")
            definitions = {row['key']: row['value'] for row in cur.fetchall()}
            combos_con_precio_float = {}
            for key, combo_data in definitions.get('combos', {}).items():
                try: combos_con_precio_float[key] = { "presas": combo_data.get("presas", {}), "productos": combo_data.get("productos", {}), "precio": float(combo_data.get("precio", "0.00")) } # Incluir productos
                except (ValueError, TypeError): combos_con_precio_float[key] = { "presas": combo_data.get("presas", {}), "productos": combo_data.get("productos", {}), "precio": 0.00 }
            inventory_data = { "inventory": {"pollosEnteros": pollos_enteros, "presas": presas, "productos": productos}, "combos": combos_con_precio_float, "presasPorPollo": definitions.get('presasPorPollo', {}) }
        return jsonify(inventory_data)
    except psycopg2.Error as e: print(f"Error DB get_inventory: {e}"); return jsonify({"success": False, "message": "Error interno (I2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/history', methods=['GET'])
def get_history():
     # ... (código igual que antes) ...
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
    # ... (código igual que antes) ...
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
    # ... (código igual que antes) ...
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
    # ... (código igual que antes) ...
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
    # ... (código igual que antes) ...
    req_data = request.get_json(); cart = req_data.get('cart')
    if not isinstance(cart, list) or not cart: return jsonify({"success": False, "message": "Carrito inválido."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (S1)."}), 500
    total_venta = Decimal('0.00'); items_para_db = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT value FROM definitions WHERE key = 'combos'")
            combos_def_json = cur.fetchone()['value'] if cur.rowcount > 0 else {}
            cur.execute("SELECT nombre_presa, cantidad FROM inventory_presas FOR UPDATE")
            current_presas = {row['nombre_presa']: row['cantidad'] for row in cur.fetchall()}
            cur.execute("SELECT nombre_producto, cantidad, precio FROM inventory_productos FOR UPDATE")
            current_productos = {row['nombre_producto']: {"cantidad": row['cantidad'], "precio": Decimal(row['precio'])} for row in cur.fetchall()}
            requerimientos = {"presas": {}, "productos": {}}; items_faltantes = []; stock_suficiente = True
            for item in cart:
                tipo = item.get('tipo'); nombre = item.get('nombre'); cantidad = item.get('cantidad', 0); display_name = item.get('display', nombre); precio_unitario = Decimal('0.00')
                if cantidad <= 0: continue
                if tipo == 'combo':
                    if nombre not in combos_def_json: stock_suficiente = False; items_faltantes.append(f"Combo '{display_name}'?"); continue
                    combo_info = combos_def_json[nombre]
                    try: precio_unitario = Decimal(str(combo_info.get('precio', '0.00')))
                    except InvalidOperation: print(f"Adv: Precio inválido combo {nombre}")
                    for p, cR in combo_info.get('presas', {}).items(): requerimientos['presas'][p] = requerimientos['presas'].get(p, 0) + cR * cantidad
                    # --- CAMBIO FUTURO: Considerar productos en combos ---
                    # for p, cR in combo_info.get('productos', {}).items(): requerimientos['productos'][p] = requerimientos['productos'].get(p, 0) + cR * cantidad
                elif tipo == 'presa': requerimientos['presas'][nombre] = requerimientos['presas'].get(nombre, 0) + cantidad
                elif tipo == 'producto':
                    if nombre not in current_productos: stock_suficiente = False; items_faltantes.append(f"Prod '{display_name}'?"); continue
                    precio_unitario = current_productos[nombre]['precio']
                    requerimientos['productos'][nombre] = requerimientos['productos'].get(nombre, 0) + cantidad
                else: stock_suficiente = False; items_faltantes.append(f"Tipo? '{display_name}'")
                total_venta += precio_unitario * cantidad
                items_para_db.append({"type": tipo, "name": nombre, "display": display_name, "quantity": cantidad, "price": precio_unitario})
            for p, cR in requerimientos['presas'].items():
                if current_presas.get(p, 0) < cR: stock_suficiente = False; items_faltantes.append(f"{p}({cR}/{current_presas.get(p, 0)})")
            for p, cR in requerimientos['productos'].items():
                 if current_productos.get(p, {}).get('cantidad', 0) < cR: stock_suficiente = False; items_faltantes.append(f"{p}({cR}/{current_productos.get(p, {}).get('cantidad', 0)})")
            if not stock_suficiente: print(f"Venta fallida stock: {items_faltantes}"); conn.rollback(); return jsonify({"success": False, "message": f"Stock insuficiente: {', '.join(items_faltantes)}"}), 400
            print("Stock OK. Procesando venta en DB...")
            cur.execute("INSERT INTO sales (total_amount) VALUES (%s) RETURNING sale_id;", (total_venta,))
            sale_id = cur.fetchone()['sale_id']; print(f"Venta registrada con ID: {sale_id}, Total: {total_venta}")
            items_sql_data = [(sale_id, i['type'], i['name'], i['display'], i['quantity'], i['price']) for i in items_para_db]
            cur.executemany("INSERT INTO sale_items (sale_id, item_type, item_name, display_name, quantity, price_per_item) VALUES (%s, %s, %s, %s, %s, %s)", items_sql_data)
            print(f"Items de la venta {sale_id} registrados.")
            print("Descontando inventario...")
            for p, cR in requerimientos['presas'].items(): cur.execute("UPDATE inventory_presas SET cantidad = cantidad - %s WHERE nombre_presa = %s", (cR, p))
            for p, cR in requerimientos['productos'].items(): cur.execute("UPDATE inventory_productos SET cantidad = cantidad - %s WHERE nombre_producto = %s", (cR, p))
            print("Inventario descontado.")
            resumen_display = ', '.join([f"{item['cantidad']}x{item.get('display', item['nombre'])}" for item in cart]); total_venta_str = f"{total_venta:.2f}"
            log_msg = f"VENTA CARRITO (ID:{sale_id}, {len(cart)} items): {resumen_display}. Total: ${total_venta_str}"
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial simple")
            conn.commit(); print(f"Venta {sale_id} confirmada y guardada.")
            return jsonify({"success": True, "message": "Venta procesada!"})
    except psycopg2.Error as e: print(f"Error DB sell_cart: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error interno al vender (S2)."}), 500
    except InvalidOperation as e: print(f"Error de precio en venta: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error en formato de precio."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/remove/pollos', methods=['POST'])
def remove_pollos():
    # ... (código igual que antes) ...
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
    # ... (código igual que antes) ...
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
    # ... (código igual que antes) ...
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
    # ... (código igual que antes) ...
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
            print(f"Query reporte: {sql} con params {params}")
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

# --- NUEVA RUTA PARA ACTUALIZAR PRECIOS ---
@app.route('/api/update/price', methods=['POST'])
def update_price():
    req_data = request.get_json()
    item_type = req_data.get('item_type') # 'producto' o 'combo'
    item_name = req_data.get('item_name') # nombre_producto o combo_key
    new_price_str = req_data.get('new_price')

    if not item_type or not item_name or new_price_str is None:
        return jsonify({"success": False, "message": "Faltan datos (tipo, nombre, precio)."}), 400

    try:
        new_price = Decimal(str(new_price_str))
        if new_price < 0:
            return jsonify({"success": False, "message": "El precio no puede ser negativo."}), 400
        new_price = new_price.quantize(Decimal("0.01")) # Asegurar 2 decimales
    except InvalidOperation:
        return jsonify({"success": False, "message": "Formato de precio inválido."}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Error DB (UP1)."}), 500

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            log_msg = ""
            if item_type == 'producto':
                cur.execute("UPDATE inventory_productos SET precio = %s WHERE nombre_producto = %s", (new_price, item_name))
                if cur.rowcount == 0:
                     conn.rollback()
                     return jsonify({"success": False, "message": f"Producto '{item_name}' no encontrado."}), 404
                log_msg = f"PRECIO ACTUALIZADO: Producto '{item_name}' a ${new_price}."
                print(log_msg)

            elif item_type == 'combo':
                # Cargar, modificar y guardar el JSON de combos
                cur.execute("SELECT value FROM definitions WHERE key = 'combos' FOR UPDATE") # Bloquear fila
                result = cur.fetchone()
                if not result:
                    conn.rollback()
                    return jsonify({"success": False, "message": "Definición de combos no encontrada."}), 404

                combos_dict = result['value']
                if item_name not in combos_dict:
                    conn.rollback()
                    return jsonify({"success": False, "message": f"Combo '{item_name}' no encontrado en definiciones."}), 404

                # Actualizar precio (guardado como string en JSON)
                combos_dict[item_name]['precio'] = str(new_price)

                # Guardar el JSON modificado
                cur.execute("UPDATE definitions SET value = %s WHERE key = 'combos'", (json.dumps(combos_dict),))
                log_msg = f"PRECIO ACTUALIZADO: Combo '{item_name}' a ${new_price}."
                print(log_msg)

            else:
                conn.rollback()
                return jsonify({"success": False, "message": "Tipo de item inválido."}), 400

            # Guardar historial y confirmar transacción
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial")
            conn.commit()
            return jsonify({"success": True, "message": log_msg})

    except psycopg2.Error as e:
        print(f"Error DB update_price: {e}"); conn.rollback()
        return jsonify({"success": False, "message": "Error interno al actualizar precio (UP2)."}), 500
    finally:
        if conn: conn.close()


# --- Ejecutar la Aplicación ---
if __name__ == '__main__':
    print("Iniciando servidor Flask para DESARROLLO LOCAL...")
    app.run(host='0.0.0.0', port=5000, debug=True)

