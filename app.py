# app.py - Backend Completo con SyntaxError Corregido y 'cantidad' consistente

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
# Configura CORS - Sé específico en producción si es posible
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Constantes ---
DEFAULT_PRESA_PRICE = Decimal("1.25")
PRESAS_KEY = 'presas_total'
PRESA_PRICE_KEY = 'presa_precio_default'
PRESAS_PER_POLLO_KEY = 'presas_por_pollo_total'
COMBOS_KEY = 'combos'

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
    print("Intentando inicializar/actualizar DB...")
    conn = get_db_connection()
    if not conn:
        print("No se pudo conectar a la DB para inicializar.")
        return
    try:
        with conn.cursor() as cur:
            print("Verificando tablas...")
            # Crear tablas (si no existen)
            cur.execute("CREATE TABLE IF NOT EXISTS users (username VARCHAR(80) PRIMARY KEY, password_hash VARCHAR(255) NOT NULL, role VARCHAR(50) NOT NULL);")
            cur.execute("CREATE TABLE IF NOT EXISTS inventory_productos (nombre_producto VARCHAR(100) PRIMARY KEY, cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0), precio NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (precio >= 0.00));")
            cur.execute("ALTER TABLE inventory_productos ADD COLUMN IF NOT EXISTS precio NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (precio >= 0.00);")
            cur.execute("CREATE TABLE IF NOT EXISTS inventory_info ( key VARCHAR(50) PRIMARY KEY, value_int INTEGER, value_numeric NUMERIC(10,2) );")
            cur.execute("CREATE TABLE IF NOT EXISTS history ( id SERIAL PRIMARY KEY, timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, message TEXT NOT NULL );")
            cur.execute("CREATE TABLE IF NOT EXISTS definitions ( key VARCHAR(50) PRIMARY KEY, value JSONB NOT NULL );")
            cur.execute("CREATE TABLE IF NOT EXISTS sales (sale_id SERIAL PRIMARY KEY, timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, total_amount NUMERIC(10, 2) NOT NULL CHECK (total_amount >= 0.00));")
            cur.execute("CREATE TABLE IF NOT EXISTS sale_items (item_id SERIAL PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(sale_id) ON DELETE CASCADE, item_type VARCHAR(50) NOT NULL, item_name VARCHAR(100) NOT NULL, display_name VARCHAR(150), quantity INTEGER NOT NULL CHECK (quantity > 0), price_per_item NUMERIC(10, 2) NOT NULL CHECK (price_per_item >= 0.00));")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sale_items_sale_id ON sale_items (sale_id);")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pending_orders (
                    order_id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    items JSONB NOT NULL,
                    nota TEXT NULL
                );
            """)
            cur.execute("ALTER TABLE pending_orders ADD COLUMN IF NOT EXISTS nota TEXT NULL;")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pending_orders_status ON pending_orders (status);")
            cur.execute("DROP TABLE IF EXISTS inventory_presas;") # Eliminar tabla obsoleta

            # Insertar datos iniciales (si no existen)
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
            cur.execute("INSERT INTO definitions (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = jsonb_deep_merge(definitions.value, EXCLUDED.value);",
                        (COMBOS_KEY, json.dumps(initial_combos)))

            cur.execute("SELECT COUNT(*) FROM history;")
            if cur.fetchone()[0] == 0:
                 ts = datetime.datetime.now(datetime.timezone.utc)
                 cur.execute("INSERT INTO history (timestamp, message) VALUES (%s, %s)", (ts, "Sistema inicializado con DB."))

            conn.commit()
            print("Base de datos inicializada/actualizada correctamente.")
    except psycopg2.Error as e:
        print(f"Error CRÍTICO durante inicialización/actualización de DB: {e}")
        conn.rollback()
    finally:
        if conn:
            conn.close()
            # print("Conexión a DB cerrada (init).") # Log opcional

def create_jsonb_deep_merge_func(conn):
    """Crea la función jsonb_deep_merge en PostgreSQL si no existe."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE OR REPLACE FUNCTION jsonb_deep_merge(jsonb, jsonb)
            RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
                SELECT jsonb_object_agg( key, CASE WHEN val1 IS NULL THEN val2 WHEN val2 IS NULL THEN val1 WHEN jsonb_typeof(val1) <> 'object' OR jsonb_typeof(val2) <> 'object' THEN val2 ELSE jsonb_deep_merge(val1, val2) END ) FROM jsonb_each($1) e1(key, val1) FULL OUTER JOIN jsonb_each($2) e2(key, val2) USING (key) $$; """)
            conn.commit()
            print("Función jsonb_deep_merge creada o ya existente.")
    except psycopg2.Error as e:
        print(f"Error creando función jsonb_deep_merge: {e}")
        conn.rollback()

with app.app_context():
    temp_conn = get_db_connection()
    if temp_conn:
        create_jsonb_deep_merge_func(temp_conn)
        temp_conn.close()
    init_db()

# --- Funciones Auxiliares ---
def add_history_db(message, conn):
    """Añade un mensaje al historial dentro de la transacción actual."""
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO history (message) VALUES (%s)", (message,))
            cur.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY timestamp DESC LIMIT 100);")
        # print(f"Historial añadido (en TX): {message}") # Log opcional
        return True
    except psycopg2.Error as e:
        print(f"Error añadiendo historial a DB (pero sin rollback aquí): {e}")
        return False

# --- Rutas API ---
@app.route('/')
def index():
    return jsonify({"status": "Backend OK"})

@app.route('/login', methods=['POST'])
def login():
    req_data = request.get_json()
    username = req_data.get('username')
    password_attempt = req_data.get('password')
    if not username or not password_attempt:
        return jsonify({"success": False, "message": "Faltan datos."}), 400
    conn = get_db_connection()
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
    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Error DB (I1)."}), 500
    inventory_data = {"inventory": {}, "combos": {}, "presasPorPolloTotal": 8}
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
                try:
                    if not isinstance(combo_data, dict): continue
                    combos_con_precio_float[key] = { "presas_necesarias": int(combo_data.get("presas_necesarias", 0)), "productos": combo_data.get("productos", {}), "precio": float(combo_data.get("precio", "0.00")) }
                except (ValueError, TypeError, AttributeError) as e:
                    print(f"Advertencia procesando combo '{key}': {e}")
                    combos_con_precio_float[key] = { "presas_necesarias": 0, "productos": {}, "precio": 0.00 }
            inventory_data = { "inventory": {"pollosEnteros": pollos_enteros, "presas_total": presas_total, "presa_precio_default": presa_precio, "productos": productos}, "combos": combos_con_precio_float, "presasPorPolloTotal": presas_por_pollo_total }
        return jsonify(inventory_data)
    except psycopg2.Error as e: print(f"Error DB get_inventory: {e}"); return jsonify({"success": False, "message": "Error interno (I2)."}), 500
    except Exception as e: print(f"Error inesperado get_inventory: {e}"); return jsonify({"success": False, "message": "Error inesperado (I3)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/history', methods=['GET'])
def get_history():
    conn = get_db_connection(); history_list = []
    if not conn: return jsonify({"success": False, "message": "Error DB (H1)."}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT timestamp, message FROM history ORDER BY timestamp DESC LIMIT 100")
            history_list = [f"[{row[0].astimezone(datetime.timezone(datetime.timedelta(hours=-5))).strftime('%Y-%m-%d %H:%M:%S') if row[0] else 'TS N/A'}] {row[1]}" for row in cur.fetchall()]
        return jsonify({"history": history_list})
    except psycopg2.Error as e: print(f"Error DB get_history: {e}"); return jsonify({"success": False, "message": "Error interno (H2)."}), 500
    finally:
        if conn: conn.close()

# --- Rutas ADD ---
@app.route('/api/add/pollos', methods=['POST'])
def add_pollos():
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (APo1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT value FROM definitions WHERE key = %s", (PRESAS_PER_POLLO_KEY,))
            result = cur.fetchone(); presas_pp = result['value'] if result and isinstance(result['value'], int) else 8
            cur.execute("INSERT INTO inventory_info (key, value_int) VALUES ('pollosEnteros', %s) ON CONFLICT (key) DO UPDATE SET value_int = inventory_info.value_int + EXCLUDED.value_int;", (cantidad,))
            presas_a_sumar = cantidad * presas_pp
            cur.execute("INSERT INTO inventory_info (key, value_int) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value_int = inventory_info.value_int + EXCLUDED.value_int;", (PRESAS_KEY, presas_a_sumar))
            log_msg = f"ENTRADA: {cantidad} pollos enteros agregados ({presas_a_sumar} presas)."
            if not add_history_db(log_msg, conn): print("Advertencia: Fallo al guardar historial add_pollos.")
            conn.commit(); print(f"Agregados {cantidad} pollos.")
            return jsonify({"success": True, "message": f"{cantidad} pollos agregados."})
    except psycopg2.Error as e: print(f"Error DB add_pollos: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al actualizar (APo2)."}), 500
    except Exception as e: print(f"Error inesperado add_pollos: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error inesperado (APo3)."}), 500
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
             if not add_history_db(log_msg, conn): print("Advertencia: Fallo al guardar historial add_presas_total.")
             conn.commit(); print(f"Agregadas {cantidad} presas generales.")
             return jsonify({"success": True, "message": f"{cantidad} presas agregadas."})
    except psycopg2.Error as e: print(f"Error DB add_presas_total: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al actualizar (APrT2)."}), 500
    except Exception as e: print(f"Error inesperado add_presas_total: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error inesperado (APrT3)."}), 500
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
            cur.execute("INSERT INTO inventory_productos (nombre_producto, cantidad, precio) VALUES (%s, %s, %s) ON CONFLICT (nombre_producto) DO UPDATE SET cantidad = inventory_productos.cantidad + EXCLUDED.cantidad, precio = EXCLUDED.precio RETURNING cantidad;", (nombre, cantidad, precio))
            result = cur.fetchone(); stock_actual = result['cantidad'] if result else 'N/A'
            log_msg = f"ENTRADA PRODUCTO: {cantidad} {nombre} (Precio: {precio}, Stock ahora: {stock_actual})."
            if not add_history_db(log_msg, conn): print(f"Advertencia: Fallo al guardar historial add_producto '{nombre}'.")
            conn.commit(); print(f"Producto: {cantidad} x {nombre} @ {precio}")
            return jsonify({"success": True, "message": f"{cantidad} '{nombre}' agregados/actualizados."})
    except psycopg2.Error as e: print(f"Error DB add_producto: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al actualizar (APd2)."}), 500
    except Exception as e: print(f"Error inesperado add_producto: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error inesperado (APd3)."}), 500
    finally:
        if conn: conn.close()

# --- RUTA DE VENTA (SELL) - CORREGIDA ---
@app.route('/api/sell', methods=['POST'])
def sell_cart():
    print("\n--- Iniciando procesamiento de venta ---")
    req_data = request.get_json()
    cart = req_data.get('cart')
    informar_cocinero = req_data.get('informar_cocinero', False)
    nota_cocinero = req_data.get('nota_cocinero', None)
    if isinstance(nota_cocinero, str):
        nota_cocinero = nota_cocinero.strip()
        if not nota_cocinero: nota_cocinero = None
    if not isinstance(cart, list) or not cart:
        print("Error: Carrito inválido o vacío recibido.")
        return jsonify({"success": False, "message": "Carrito inválido o vacío."}), 400
    print(f"Carrito recibido: {len(cart)} items. Informar cocina: {informar_cocinero}. Nota: '{nota_cocinero}'")
    print(f"Contenido crudo del carrito recibido: {json.dumps(cart)}")
    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Error de conexión interna (S1)."}), 500
    total_venta = Decimal('0.00'); items_para_db = []; requerimientos = {"presas_total": 0, "productos": {}}; items_faltantes = []; stock_suficiente = True; sale_id = None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            print("Obteniendo definiciones y estado actual del inventario CON BLOQUEO (FOR UPDATE)...")
            cur.execute("SELECT key, value FROM definitions WHERE key IN (%s, %s)", (COMBOS_KEY, PRESAS_PER_POLLO_KEY))
            definitions = {row['key']: row['value'] for row in cur.fetchall()}
            combos_def_json = definitions.get(COMBOS_KEY, {})
            cur.execute("SELECT key, value_int, value_numeric FROM inventory_info WHERE key IN (%s, %s) FOR UPDATE", (PRESAS_KEY, PRESA_PRICE_KEY))
            info_data = {row['key']: row['value_int'] if row['value_int'] is not None else Decimal(row['value_numeric']) for row in cur.fetchall()}
            current_presas_total = info_data.get(PRESAS_KEY, 0)
            presa_precio_default = info_data.get(PRESA_PRICE_KEY, DEFAULT_PRESA_PRICE)
            cur.execute("SELECT nombre_producto, cantidad, precio FROM inventory_productos FOR UPDATE")
            current_productos = {row['nombre_producto']: {"cantidad": row['cantidad'], "precio": Decimal(row['precio'])} for row in cur.fetchall()}
            print(f"Inventario actual bloqueado: Presas={current_presas_total}, PrecioPresa={presa_precio_default}")
            print("Calculando requerimientos y total de la venta...")
            for item_index, item in enumerate(cart):
                if not isinstance(item, dict):
                    print(f"    Error: Item {item_index+1} no es dict: {item}. Saltando."); items_faltantes.append(f"Item inválido {item_index+1}"); stock_suficiente = False; continue
                tipo = item.get('tipo'); nombre = item.get('nombre')
                # ***** CORRECCIÓN CLAVE *****
                cantidad = item.get('cantidad') # Usar 'cantidad' (español)
                # ***** FIN CORRECCIÓN *****
                display_name = item.get('display', nombre)
                print(f"  Procesando item {item_index+1}/{len(cart)}: {cantidad} x '{nombre}' (Tipo: {tipo})")
                if not isinstance(cantidad, int) or cantidad <= 0:
                    print(f"    Error: Cantidad inválida ({cantidad}, tipo: {type(cantidad).__name__}) para '{nombre}'. Saltando."); items_faltantes.append(f"Cantidad inválida para '{display_name}'"); stock_suficiente = False; continue
                precio_unitario = Decimal('0.00')
                if tipo == 'combo':
                    if nombre not in combos_def_json: print(f"    Error: Combo '{nombre}' no definido."); items_faltantes.append(f"Combo '{display_name}' no definido"); stock_suficiente = False; continue
                    combo_info = combos_def_json[nombre]
                    if not isinstance(combo_info, dict): print(f"    Error: Definición combo '{nombre}' inválida."); items_faltantes.append(f"Definición inválida '{display_name}'"); stock_suficiente = False; continue
                    try: precio_str = combo_info.get('precio', '0.00'); precio_unitario = Decimal(str(precio_str)).quantize(Decimal("0.01")); assert precio_unitario >= 0
                    except (InvalidOperation, AssertionError): print(f"    Advertencia: Precio inválido combo '{nombre}'. Usando 0.00."); precio_unitario = Decimal('0.00')
                    presas_req_combo = int(combo_info.get('presas_necesarias', 0)) * cantidad; requerimientos['presas_total'] += presas_req_combo
                    productos_req_combo = combo_info.get('productos', {});
                    if isinstance(productos_req_combo, dict):
                        for p_combo, c_req_unitario in productos_req_combo.items(): requerimientos['productos'][p_combo] = requerimientos['productos'].get(p_combo, 0) + int(c_req_unitario) * cantidad
                    else: print(f"    Advertencia: 'productos' en combo '{nombre}' no es dict.")
                elif tipo == 'presa':
                    precio_unitario = presa_precio_default.quantize(Decimal("0.01")); requerimientos['presas_total'] += cantidad
                elif tipo == 'producto':
                    if nombre not in current_productos: print(f"    Error: Producto '{nombre}' no existe."); items_faltantes.append(f"Producto '{display_name}' no existe"); stock_suficiente = False; continue
                    try: precio_unitario = current_productos[nombre]['precio'].quantize(Decimal("0.01"))
                    except KeyError: print(f"    Error: Precio no encontrado producto '{nombre}'. Usando 0.00"); precio_unitario = Decimal('0.00')
                    requerimientos['productos'][nombre] = requerimientos['productos'].get(nombre, 0) + cantidad
                else: print(f"    Error: Tipo desconocido '{tipo}'."); items_faltantes.append(f"Tipo desconocido '{display_name}'"); stock_suficiente = False; continue
                item_total = precio_unitario * cantidad; total_venta += item_total
                items_para_db.append({"type": tipo, "name": nombre, "display": display_name, "quantity": cantidad, "price": float(precio_unitario)})
                print(f"    Subtotal item: {item_total:.2f}. Total acum: {total_venta:.2f}")
            print(f"\nReq. totales: Presas={requerimientos['presas_total']}, Productos={requerimientos['productos']}. Total Venta: {total_venta:.2f}")
            print("Verificando stock suficiente...")
            if current_presas_total < requerimientos['presas_total']: stock_suficiente = False; items_faltantes.append(f"Presas (Req: {requerimientos['presas_total']}/Disp: {current_presas_total})")
            for p_req, c_req in requerimientos['productos'].items():
                 stock_disponible_prod = current_productos.get(p_req, {}).get('cantidad', 0)
                 if stock_disponible_prod < c_req: stock_suficiente = False; items_faltantes.append(f"{p_req} (Req: {c_req}/Disp: {stock_disponible_prod})")
            if not stock_suficiente:
                error_msg = f"Stock insuficiente: {', '.join(items_faltantes)}" if items_faltantes else "Error en datos carrito."
                print(f"Error final: {error_msg}"); conn.rollback(); print("ROLLBACK por stock/cantidad inválida."); return jsonify({"success": False, "message": error_msg}), 400
            print("Stock OK. Registrando venta y descontando...")
            cur.execute("INSERT INTO sales (total_amount) VALUES (%s) RETURNING sale_id;", (total_venta,)); sale_id = cur.fetchone()['sale_id']; print(f"Venta ID: {sale_id} registrada.")
            if items_para_db:
                items_sql_data = [(sale_id, i['type'], i['name'], i['display'], i['quantity'], Decimal(str(i['price']))) for i in items_para_db]
                cur.executemany("INSERT INTO sale_items (sale_id, item_type, item_name, display_name, quantity, price_per_item) VALUES (%s, %s, %s, %s, %s, %s)", items_sql_data); print("Items de venta registrados.")
            if requerimientos['presas_total'] > 0:
                print(f"Descontando {requerimientos['presas_total']} presas..."); cur.execute("UPDATE inventory_info SET value_int = value_int - %s WHERE key = %s AND value_int >= %s", (requerimientos['presas_total'], PRESAS_KEY, requerimientos['presas_total']))
                if cur.rowcount == 0: print("¡ERROR CRÍTICO descontando presas!"); raise psycopg2.Error("Fallo al descontar presas.")
                print("Presas descontadas OK.")
            if requerimientos['productos']:
                print("Descontando productos...");
                for p_desc, c_desc in requerimientos['productos'].items():
                    print(f"  Descontando {c_desc} x '{p_desc}'..."); cur.execute("UPDATE inventory_productos SET cantidad = cantidad - %s WHERE nombre_producto = %s AND cantidad >= %s", (c_desc, p_desc, c_desc))
                    if cur.rowcount == 0: stock_actual_fallo = current_productos.get(p_desc, {}).get('cantidad', '???'); print(f"¡ERROR CRÍTICO descontando '{p_desc}'! Stock: {stock_actual_fallo}. Req: {c_desc}."); raise psycopg2.Error(f"Fallo al descontar '{p_desc}'.")
                print("Productos descontados OK.")
            if informar_cocinero:
                print("Enviando a cocina..."); items_json_cocina = json.dumps(items_para_db)
                try: cur.execute("INSERT INTO pending_orders (items, nota) VALUES (%s, %s) RETURNING order_id;", (items_json_cocina, nota_cocinero)); order_id_cocina = cur.fetchone()['order_id']; print(f"Orden enviada a cocina ID: {order_id_cocina}")
                except psycopg2.Error as e_cocina: print(f"¡ERROR enviando a cocina! Venta ID {sale_id}. Error: {e_cocina}. VENTA CONTINÚA.")
            resumen_display = ', '.join([f"{i.get('quantity', '?')}x{i.get('display', i.get('name', '?'))}" for i in items_para_db]); total_venta_str = f"{total_venta:.2f}"
            log_msg = f"VENTA CARRITO (ID:{sale_id}, {len(items_para_db)} items): {resumen_display}. Total: ${total_venta_str}"
            if informar_cocinero: log_msg += " [Enviado a Cocina]"
            if nota_cocinero: log_msg += f" [Nota: {nota_cocinero[:30]}{'...' if len(nota_cocinero)>30 else ''}]"
            if not add_history_db(log_msg, conn): print(f"Advertencia: Fallo al guardar historial venta ID {sale_id}.")
            conn.commit(); print(f"--- Venta ID {sale_id} COMPLETADA (COMMIT) ---")
            return jsonify({"success": True, "message": "Venta procesada exitosamente!"})
    except psycopg2.Error as e: error_type = type(e).__name__; error_msg_db = f"Error DB venta (ID: {sale_id if sale_id else 'N/A'}): {error_type} - {e}"; print(error_msg_db); conn.rollback(); print("ROLLBACK por error DB."); return jsonify({"success": False, "message": f"Error interno servidor ({error_type})."}), 500
    except (InvalidOperation, ValueError, TypeError, KeyError, AssertionError) as e: error_type = type(e).__name__; error_msg_val = f"Error datos/validación venta (ID: {sale_id if sale_id else 'N/A'}): {error_type} - {e}"; print(error_msg_val); conn.rollback(); print("ROLLBACK por error datos/validación."); return jsonify({"success": False, "message": f"Error datos carrito/definiciones ({error_type})."}), 400
    except Exception as e: error_type = type(e).__name__; error_msg_ines = f"Error inesperado venta (ID: {sale_id if sale_id else 'N/A'}): {error_type} - {e}"; print(error_msg_ines); conn.rollback(); print("ROLLBACK por error inesperado."); return jsonify({"success": False, "message": "Error inesperado servidor."}), 500
    finally:
        if conn: conn.close()

# --- Rutas REMOVE ---
@app.route('/api/remove/pollos', methods=['POST'])
def remove_pollos():
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (RPo1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT value FROM definitions WHERE key = %s", (PRESAS_PER_POLLO_KEY,))
            result = cur.fetchone(); presas_pp = result['value'] if result and isinstance(result['value'], int) else 8
            presas_a_quitar = cantidad * presas_pp
            cur.execute("SELECT value_int FROM inventory_info WHERE key = %s FOR UPDATE", (PRESAS_KEY,))
            result_presas = cur.fetchone(); current_presas_total = result_presas['value_int'] if result_presas else 0
            cur.execute("SELECT value_int FROM inventory_info WHERE key = 'pollosEnteros' FOR UPDATE",)
            result_pollos = cur.fetchone(); current_pollos = result_pollos['value_int'] if result_pollos else 0
            if current_presas_total < presas_a_quitar or current_pollos < cantidad:
                msg = f"Stock insuf. Disp: {current_pollos} pollos, {current_presas_total} presas. Req quitar: {cantidad} pollos ({presas_a_quitar} presas)."
                print(msg); conn.rollback(); return jsonify({"success": False, "message": msg}), 400
            cur.execute("UPDATE inventory_info SET value_int = value_int - %s WHERE key = 'pollosEnteros' AND value_int >= %s", (cantidad, cantidad))
            if cur.rowcount == 0: raise psycopg2.Error("Fallo al descontar pollos")
            cur.execute("UPDATE inventory_info SET value_int = value_int - %s WHERE key = %s AND value_int >= %s", (presas_a_quitar, PRESAS_KEY, presas_a_quitar))
            if cur.rowcount == 0: raise psycopg2.Error("Fallo al descontar presas asociadas a pollos")
            log_msg = f"ELIMINACIÓN: {cantidad} pollos enteros (merma, {presas_a_quitar} presas)."
            if not add_history_db(log_msg, conn): print("Advertencia: Fallo historial remove_pollos.")
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
            cur.execute("UPDATE inventory_info SET value_int = value_int - %s WHERE key = %s AND value_int >= %s RETURNING value_int", (cantidad, PRESAS_KEY, cantidad))
            result = cur.fetchone()
            if result is None:
                 cur.execute("SELECT value_int FROM inventory_info WHERE key = %s", (PRESAS_KEY,))
                 stock_actual = cur.fetchone(); stock_disp = stock_actual['value_int'] if stock_actual else 0
                 msg = f"Stock insuficiente de presas (Disp: {stock_disp}, Req: {cantidad})"; conn.rollback(); return jsonify({"success": False, "message": msg}), 400
            log_msg = f"ELIMINACIÓN: {cantidad} presas generales (merma). Stock restante: {result['value_int']}."
            if not add_history_db(log_msg, conn): print("Advertencia: Fallo historial remove_presas_total.")
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
                msg = f"Stock insuf. o producto '{nombre}' no existe (Disp: {stock_disp}, Req: {cantidad})"; conn.rollback(); return jsonify({"success": False, "message": msg}), 400
            stock_restante = result['cantidad']
            log_msg = f"ELIMINACIÓN PRODUCTO: {cantidad} {nombre} (merma). Stock restante: {stock_restante}."
            if not add_history_db(log_msg, conn): print(f"Advertencia: Fallo historial remove_producto '{nombre}'.")
            conn.commit(); print(f"Eliminado producto: {cantidad} x {nombre} (merma).")
            return jsonify({"success": True, "message": f"{cantidad} '{nombre}' eliminados." })
    except psycopg2.Error as e: print(f"Error DB remove_producto: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error al eliminar producto (RPd2)."}), 500
    finally:
        if conn: conn.close()

# --- Ruta REPORTES ---
@app.route('/api/reports/sales', methods=['GET'])
def get_sales_report():
    start_date_str = request.args.get('start_date'); end_date_str = request.args.get('end_date')
    start_date = None; end_date = None
    if start_date_str:
        try: start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except ValueError: return jsonify({"success": False, "message": "Formato fecha inicial inválido."}), 400
    if end_date_str:
        try: end_dt = datetime.datetime.strptime(end_date_str, '%Y-%m-%d'); end_date = datetime.datetime.combine(end_dt.date(), datetime.time.max)
        except ValueError: return jsonify({"success": False, "message": "Formato fecha final inválido."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (R1)."}), 500
    sales_list = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            sql = "SELECT s.sale_id, s.timestamp, s.total_amount, si.item_type, si.display_name, si.quantity, si.price_per_item FROM sales s JOIN sale_items si ON s.sale_id = si.sale_id"
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

# --- Ruta UPDATE PRICE ---
@app.route('/api/update/price', methods=['POST'])
def update_price():
    req_data = request.get_json(); item_type = req_data.get('item_type'); item_name = req_data.get('item_name'); new_price_str = req_data.get('new_price')
    if not item_type or new_price_str is None or (item_type != 'presa' and not item_name): return jsonify({"success": False, "message": "Faltan datos."}), 400
    if item_type not in ['producto', 'combo', 'presa']: return jsonify({"success": False, "message": "Tipo inválido."}), 400
    try:
        new_price = Decimal(str(new_price_str)); assert new_price >= 0; new_price = new_price.quantize(Decimal("0.01"))
    except (InvalidOperation, AssertionError): return jsonify({"success": False, "message": "Formato/valor precio inválido."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (UP1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            log_msg = ""; rowcount = -1; item_display = item_name
            if item_type == 'producto':
                cur.execute("UPDATE inventory_productos SET precio = %s WHERE nombre_producto = %s", (new_price, item_name)); rowcount = cur.rowcount
                if rowcount > 0: log_msg = f"PRECIO ACTUALIZADO: Producto '{item_name}' a ${new_price}."
            elif item_type == 'presa':
                cur.execute("INSERT INTO inventory_info (key, value_numeric) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value_numeric = EXCLUDED.value_numeric;", (PRESA_PRICE_KEY, new_price)); rowcount = 1
                log_msg = f"PRECIO ACTUALIZADO: Precio Presa General a ${new_price}."; item_display = "Presa General"
            elif item_type == 'combo':
                cur.execute("SELECT value FROM definitions WHERE key = 'combos' FOR UPDATE"); result = cur.fetchone()
                if not result: conn.rollback(); return jsonify({"success": False, "message": "Definición combos no encontrada."}), 404
                combos_dict = result['value']
                if item_name not in combos_dict: conn.rollback(); return jsonify({"success": False, "message": f"Combo '{item_name}' no encontrado."}), 404
                combos_dict[item_name]['precio'] = str(new_price)
                cur.execute("UPDATE definitions SET value = %s WHERE key = 'combos'", (json.dumps(combos_dict),)); rowcount = cur.rowcount
                log_msg = f"PRECIO ACTUALIZADO: Combo '{item_name}' a ${new_price}."
            if rowcount == 0 and item_type == 'producto': conn.rollback(); return jsonify({"success": False, "message": f"Producto '{item_name}' no encontrado."}), 404
            if not log_msg: conn.rollback(); return jsonify({"success": False, "message": f"Error al actualizar precio para {item_display}."}), 500
            print(log_msg);
            if not add_history_db(log_msg, conn): print(f"Advertencia: Fallo historial update_price '{item_display}'.")
            conn.commit(); return jsonify({"success": True, "message": log_msg})
    except psycopg2.Error as e: print(f"Error DB update_price: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error interno (UP2)."}), 500
    finally:
        if conn: conn.close()

# --- Rutas CUSTOM COMBOS ---
@app.route('/api/add/custom_combo', methods=['POST'])
def add_custom_combo():
    req_data = request.get_json(); combo_name = req_data.get('name', '').strip(); combo_price_str = req_data.get('price'); items = req_data.get('items')
    if not combo_name: return jsonify({"success": False, "message": "Nombre requerido."}), 400
    if not isinstance(items, list) or not items: return jsonify({"success": False, "message": "Items requeridos."}), 400
    try: combo_price = Decimal(str(combo_price_str)); assert combo_price >= 0; combo_price = combo_price.quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, AssertionError): return jsonify({"success": False, "message": "Formato/valor precio inválido."}), 400
    normalized_name = re.sub(r'\s+', '_', combo_name.lower()); normalized_name = re.sub(r'[^\w-]', '', normalized_name); combo_key = f"custom_{normalized_name}"
    if not combo_key.replace('custom_', ''): return jsonify({"success": False, "message": "Nombre inválido."}), 400
    new_combo_data = {"presas_necesarias": 0, "productos": {}, "precio": str(combo_price)}; valid_item_types = ['presa', 'producto']
    conn_check = get_db_connection();
    if not conn_check: return jsonify({"success": False, "message": "Error DB (CC_Check1)."}), 500
    try:
        # CORREGIDO: Indentación y variable cur_check
        with conn_check.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur_check:
             cur_check.execute("SELECT nombre_producto FROM inventory_productos")
             valid_productos = {row['nombre_producto'] for row in cur_check.fetchall()}
    except psycopg2.Error as e: print(f"Error DB validando items: {e}"); return jsonify({"success": False, "message": "Error interno (CC_Check2)."}), 500
    finally:
        if conn_check: conn_check.close()
    for item in items:
        item_type = item.get('type', '').lower(); item_name = item.get('name')
        # CORREGIDO: Usar 'cantidad' consistentemente
        item_qty = item.get('cantidad')
        if item_type not in valid_item_types or not item_name or not isinstance(item_qty, int) or item_qty <= 0: return jsonify({"success": False, "message": f"Item inválido en combo: {item}"}), 400
        if item_type == 'presa': new_combo_data['presas_necesarias'] += item_qty
        elif item_type == 'producto':
            item_name_cap = item_name.capitalize()
            if item_name_cap not in valid_productos: return jsonify({"success": False, "message": f"Producto '{item_name_cap}' no válido."}), 400
            new_combo_data['productos'][item_name_cap] = new_combo_data['productos'].get(item_name_cap, 0) + item_qty
    if new_combo_data['presas_necesarias'] == 0 and not new_combo_data['productos']: return jsonify({"success": False, "message": "Combo debe tener items."}), 400
    conn = get_db_connection();
    if not conn: return jsonify({"success": False, "message": "Error DB (CC1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT value FROM definitions WHERE key = 'combos' FOR UPDATE"); result = cur.fetchone(); combos_dict = result['value'] if result else {}
            if combo_key in combos_dict: conn.rollback(); return jsonify({"success": False, "message": f"Combo similar ya existe ('{combo_key}')."}), 400
            combos_dict[combo_key] = new_combo_data
            cur.execute("INSERT INTO definitions (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;", ('combos', json.dumps(combos_dict)))
            log_msg = f"COMBO PERSONALIZADO AÑADIDO: '{combo_name}' (ID: {combo_key}, Precio: ${combo_price})."
            if not add_history_db(log_msg, conn): print("Advertencia: Fallo historial add_custom_combo.")
            conn.commit(); print(log_msg); return jsonify({"success": True, "message": f"Combo '{combo_name}' añadido."})
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
            cur.execute("SELECT value FROM definitions WHERE key = 'combos' FOR UPDATE"); result = cur.fetchone()
            if not result: conn.rollback(); return jsonify({"success": False, "message": "Definición combos no encontrada."}), 404
            combos_dict = result['value']
            if combo_key not in combos_dict: conn.rollback(); return jsonify({"success": False, "message": f"Combo '{combo_key}' no encontrado."}), 404
            combo_name_display = combo_key.replace('custom_', '').replace('_', ' ').capitalize()
            del combos_dict[combo_key]; print(f"Combo '{combo_key}' eliminado.")
            cur.execute("UPDATE definitions SET value = %s WHERE key = 'combos'", (json.dumps(combos_dict),))
            log_msg = f"COMBO PERSONALIZADO ELIMINADO: '{combo_name_display}' (ID: {combo_key})."
            if not add_history_db(log_msg, conn): print("Advertencia: Fallo historial remove_custom_combo.")
            conn.commit(); print(log_msg); return jsonify({"success": True, "message": f"Combo '{combo_name_display}' eliminado."})
    except psycopg2.Error as e: print(f"Error DB remove_custom_combo: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error interno (RC2)."}), 500
    finally:
        if conn: conn.close()

# --- Rutas ORDERS ---
@app.route('/api/orders/pending', methods=['GET'])
def get_pending_orders():
    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Error DB (O1)."}), 500
    orders = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT order_id, timestamp, items, nota FROM pending_orders WHERE status = 'pending' ORDER BY timestamp ASC")
            for row in cur.fetchall():
                items_list = []; items_data = row['items']
                try:
                    if isinstance(items_data, str): items_data = json.loads(items_data)
                    if not isinstance(items_data, list): items_data = []
                    for item in items_data:
                        if isinstance(item, dict):
                          try: item['price'] = float(item.get('price', 0.0))
                          except (ValueError, TypeError): item['price'] = 0.0
                          # CORREGIDO: Usar 'cantidad' consistentemente
                          item['quantity'] = int(item.get('cantidad', 0))
                          items_list.append(item)
                        else: print(f"Advertencia: Item inválido (no dict) en orden {row['order_id']}: {item}")
                except (json.JSONDecodeError, TypeError, ValueError) as json_err:
                     print(f"Error parseando items orden {row['order_id']}: {json_err}"); items_list.append({"display": "Error items", "quantity": 1, "type": "error", "price": 0.0})
                orders.append({"order_id": row['order_id'], "timestamp": row['timestamp'].isoformat(), "items": items_list, "nota": row['nota']})
        return jsonify({"success": True, "orders": orders})
    except psycopg2.Error as e: print(f"Error DB get_pending_orders: {e}"); return jsonify({"success": False, "message": "Error interno (O2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/orders/complete/<int:order_id>', methods=['POST'])
def complete_order(order_id):
    print(f"Solicitud para completar orden ID: {order_id}")
    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Error DB (OC1)."}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE pending_orders SET status = 'completed' WHERE order_id = %s AND status = 'pending'", (order_id,))
            if cur.rowcount == 0: conn.rollback(); print(f"Orden {order_id} no encontrada/pendiente."); return jsonify({"success": False, "message": "Orden no encontrada o ya completada."}), 404
            log_msg = f"COCINA: Orden ID:{order_id} marcada como terminada."
            if not add_history_db(log_msg, conn): print(f"Advertencia: Fallo historial complete_order {order_id}.")
            conn.commit(); print(f"Orden {order_id} completada.")
            return jsonify({"success": True, "message": f"Orden {order_id} completada."})
    except psycopg2.Error as e: print(f"Error DB complete_order: {e}"); conn.rollback(); return jsonify({"success": False, "message": "Error interno (OC2)."}), 500
    finally:
        if conn: conn.close()

# --- Ejecutar la Aplicación ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False') == 'True'
    print(f"Iniciando servidor Flask. Puerto: {port}, Modo Debug: {debug_mode}")
    app.run(host='0.0.0.0', port=port, debug=debug_mode, use_reloader=debug_mode)
