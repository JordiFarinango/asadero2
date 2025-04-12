# app.py - Backend con Logging Mejorado para Depuración

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
# Asegúrate de que tu URL de Netlify esté aquí en producción si es posible
# Ejemplo: origins=["https://tu-frontend.netlify.app", "http://localhost:8000"] # O el puerto que uses localmente
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
        print("Conexión a DB establecida.")
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
            # Verificar/Crear todas las tablas (igual que antes)
            print("Verificando tabla 'users'...")
            cur.execute("CREATE TABLE IF NOT EXISTS users (username VARCHAR(80) PRIMARY KEY, password_hash VARCHAR(255) NOT NULL, role VARCHAR(50) NOT NULL);")
            print("Verificando tabla 'inventory_productos'...")
            cur.execute("CREATE TABLE IF NOT EXISTS inventory_productos (nombre_producto VARCHAR(100) PRIMARY KEY, cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0), precio NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (precio >= 0.00));")
            cur.execute("ALTER TABLE inventory_productos ADD COLUMN IF NOT EXISTS precio NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (precio >= 0.00);") # Asegurar columna precio
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
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sale_items_sale_id ON sale_items (sale_id);") # Index para eficiencia
            print("Verificando tabla 'pending_orders'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pending_orders (
                    order_id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- 'pending', 'completed'
                    items JSONB NOT NULL,
                    nota TEXT NULL
                );
            """)
            cur.execute("ALTER TABLE pending_orders ADD COLUMN IF NOT EXISTS nota TEXT NULL;") # Asegurar columna nota
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pending_orders_status ON pending_orders (status);") # Index para eficiencia
            cur.execute("DROP TABLE IF EXISTS inventory_presas;") # Eliminar tabla obsoleta si existe

            # --- Insertar/Actualizar datos iniciales (igual que antes) ---
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
                # Puedes añadir más combos predefinidos aquí si quieres
            }
            # Usar DO UPDATE para asegurar que los combos base siempre estén actualizados si cambian aquí
            cur.execute("INSERT INTO definitions (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = jsonb_deep_merge(definitions.value, EXCLUDED.value);",
                        (COMBOS_KEY, json.dumps(initial_combos)))

            # Añadir historial inicial solo si la tabla está vacía
            cur.execute("SELECT COUNT(*) FROM history;")
            if cur.fetchone()[0] == 0:
                 ts = datetime.datetime.now(datetime.timezone.utc)
                 cur.execute("INSERT INTO history (timestamp, message) VALUES (%s, %s)", (ts, "Sistema inicializado con DB."))

            conn.commit()
            print("Base de datos inicializada/actualizada correctamente.")
    except psycopg2.Error as e:
        print(f"Error CRÍTICO durante inicialización/actualización de DB: {e}")
        conn.rollback() # Asegurar rollback si falla init
    finally:
        if conn:
            conn.close()
            print("Conexión a DB cerrada (init).")

# Crear función para merge profundo de JSON (necesaria para el INSERT... ON CONFLICT... DO UPDATE de combos)
def create_jsonb_deep_merge_func(conn):
    """Crea la función jsonb_deep_merge en PostgreSQL si no existe."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE OR REPLACE FUNCTION jsonb_deep_merge(jsonb, jsonb)
            RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
                SELECT
                    jsonb_object_agg(
                        key,
                        CASE
                            WHEN val1 IS NULL THEN val2
                            WHEN val2 IS NULL THEN val1
                            WHEN jsonb_typeof(val1) <> 'object' OR jsonb_typeof(val2) <> 'object' THEN val2
                            ELSE jsonb_deep_merge(val1, val2)
                        END
                    )
                FROM jsonb_each($1) e1(key, val1)
                FULL OUTER JOIN jsonb_each($2) e2(key, val2) USING (key)
            $$;
            """)
            conn.commit()
            print("Función jsonb_deep_merge creada o ya existente.")
    except psycopg2.Error as e:
        print(f"Error creando función jsonb_deep_merge: {e}")
        conn.rollback()


# Llamar a init_db() y crear función al inicio
with app.app_context():
    temp_conn = get_db_connection()
    if temp_conn:
        create_jsonb_deep_merge_func(temp_conn)
        temp_conn.close()
        print("Conexión temporal para crear función cerrada.")
    init_db()


# --- Funciones Auxiliares ---
def add_history_db(message, conn):
    """Añade un mensaje al historial dentro de la transacción actual."""
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO history (message) VALUES (%s)", (message,))
            # Limitar historial a los últimos 100 registros para evitar que crezca indefinidamente
            cur.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY timestamp DESC LIMIT 100);")
        print(f"Historial añadido (en TX): {message}")
        return True
    except psycopg2.Error as e:
        # No hacer rollback aquí, dejar que la función principal lo maneje
        print(f"Error añadiendo historial a DB (pero sin rollback aquí): {e}")
        return False # Indicar fallo

# --- Rutas API (Login, Inventory, History sin cambios significativos) ---
@app.route('/')
def index():
    # Podrías servir el index.html directamente desde Flask si no usas Netlify
    # return render_template('index.html')
    # O simplemente devolver un OK si Netlify maneja el frontend
    return jsonify({"status": "Backend OK"})

@app.route('/login', methods=['POST'])
def login():
    req_data = request.get_json()
    username = req_data.get('username')
    password_attempt = req_data.get('password')

    if not username or not password_attempt:
        return jsonify({"success": False, "message": "Faltan datos de usuario o contraseña."}), 400

    conn = get_db_connection()
    user_info = None
    if not conn:
        return jsonify({"success": False, "message": "Error de conexión interna (L1)."}), 500

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT password_hash, role FROM users WHERE username = %s", (username,))
            user_info = cur.fetchone()

        if user_info and user_info['password_hash'] and check_password_hash(user_info['password_hash'], password_attempt):
            print(f"Login exitoso para usuario: {username}, Rol: {user_info.get('role', 'vendedor')}")
            return jsonify({"success": True, "role": user_info.get('role', 'vendedor')})
        else:
            print(f"Login fallido para usuario: {username}")
            return jsonify({"success": False, "message": "Credenciales incorrectas."}), 401
    except psycopg2.Error as e:
        print(f"Error de base de datos durante login para {username}: {e}")
        return jsonify({"success": False, "message": "Error interno del servidor (L2)."}), 500
    finally:
        if conn:
            conn.close()
            print("Conexión a DB cerrada (login).")


@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Error de conexión interna (I1)."}), 500

    inventory_data = {"inventory": {}, "combos": {}, "presasPorPolloTotal": 8} # Default structure

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Obtener info general (presas, precio presa, pollos)
            cur.execute("SELECT key, value_int, value_numeric FROM inventory_info WHERE key IN (%s, %s, %s)",
                        (PRESAS_KEY, PRESA_PRICE_KEY, 'pollosEnteros'))
            info_data = {row['key']: row['value_int'] if row['value_int'] is not None else float(row['value_numeric'])
                         for row in cur.fetchall()}

            presas_total = info_data.get(PRESAS_KEY, 0)
            presa_precio = info_data.get(PRESA_PRICE_KEY, float(DEFAULT_PRESA_PRICE))
            pollos_enteros = info_data.get('pollosEnteros', 0)

            # Obtener productos
            cur.execute("SELECT nombre_producto, cantidad, precio FROM inventory_productos")
            productos = {row['nombre_producto']: {"cantidad": row['cantidad'], "precio": float(row['precio'])}
                         for row in cur.fetchall()}

            # Obtener definiciones (combos, presas por pollo)
            cur.execute("SELECT key, value FROM definitions")
            definitions = {row['key']: row['value'] for row in cur.fetchall()}

            combos_def = definitions.get(COMBOS_KEY, {})
            presas_por_pollo_total = definitions.get(PRESAS_PER_POLLO_KEY, 8) # Default 8 if not set

            # Convertir precios de combos a float para el frontend
            combos_con_precio_float = {}
            for key, combo_data in combos_def.items():
                try:
                    # Asegurarse de que combo_data sea un diccionario
                    if not isinstance(combo_data, dict):
                        print(f"Advertencia: La definición del combo '{key}' no es un diccionario válido.")
                        continue # Saltar este combo si está mal formado

                    combos_con_precio_float[key] = {
                        "presas_necesarias": int(combo_data.get("presas_necesarias", 0)),
                        "productos": combo_data.get("productos", {}),
                        "precio": float(combo_data.get("precio", "0.00"))
                    }
                except (ValueError, TypeError, AttributeError) as e:
                    print(f"Advertencia: Error procesando precio/datos del combo '{key}': {e}. Usando defaults.")
                    combos_con_precio_float[key] = {
                        "presas_necesarias": 0,
                        "productos": {},
                        "precio": 0.00
                    }

            inventory_data = {
                "inventory": {
                    "pollosEnteros": pollos_enteros,
                    "presas_total": presas_total,
                    "presa_precio_default": presa_precio,
                    "productos": productos
                },
                "combos": combos_con_precio_float,
                "presasPorPolloTotal": presas_por_pollo_total
            }
        # print("Inventario enviado:", inventory_data) # Descomentar para debug detallado
        return jsonify(inventory_data)
    except psycopg2.Error as e:
        print(f"Error de base de datos en get_inventory: {e}")
        return jsonify({"success": False, "message": "Error interno del servidor (I2)."}), 500
    except Exception as e: # Capturar otros posibles errores
        print(f"Error inesperado en get_inventory: {type(e).__name__} - {e}")
        return jsonify({"success": False, "message": "Error inesperado del servidor (I3)."}), 500
    finally:
        if conn:
            conn.close()
            # print("Conexión a DB cerrada (get_inventory).") # Puede ser muy verboso

@app.route('/api/history', methods=['GET'])
def get_history():
    conn = get_db_connection()
    history_list = []
    if not conn:
        return jsonify({"success": False, "message": "Error de conexión interna (H1)."}), 500

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT timestamp, message FROM history ORDER BY timestamp DESC LIMIT 100")
            # Formatear fecha/hora localmente (ej. Ecuador -05:00)
            history_list = [f"[{row[0].astimezone(datetime.timezone(datetime.timedelta(hours=-5))).strftime('%Y-%m-%d %H:%M:%S') if row[0] else 'TS N/A'}] {row[1]}"
                            for row in cur.fetchall()]
        return jsonify({"history": history_list})
    except psycopg2.Error as e:
        print(f"Error de base de datos en get_history: {e}")
        return jsonify({"success": False, "message": "Error interno del servidor (H2)."}), 500
    finally:
        if conn:
            conn.close()
            # print("Conexión a DB cerrada (get_history).")

# --- Rutas ADD (sin cambios mayores, se asume funcionan) ---
@app.route('/api/add/pollos', methods=['POST'])
def add_pollos():
    req_data = request.get_json()
    cantidad = req_data.get('quantity')

    if not isinstance(cantidad, int) or cantidad <= 0:
        return jsonify({"success": False, "message": "Cantidad inválida."}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Error de conexión interna (APo1)."}), 500

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Obtener presas por pollo
            cur.execute("SELECT value FROM definitions WHERE key = %s", (PRESAS_PER_POLLO_KEY,))
            result = cur.fetchone()
            presas_pp = result['value'] if result and isinstance(result['value'], int) else 8 # Default 8

            # Actualizar pollos
            cur.execute("""
                INSERT INTO inventory_info (key, value_int) VALUES ('pollosEnteros', %s)
                ON CONFLICT (key) DO UPDATE SET value_int = inventory_info.value_int + EXCLUDED.value_int;
            """, (cantidad,))

            # Actualizar presas totales
            presas_a_sumar = cantidad * presas_pp
            cur.execute("""
                INSERT INTO inventory_info (key, value_int) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value_int = inventory_info.value_int + EXCLUDED.value_int;
            """, (PRESAS_KEY, presas_a_sumar))

            log_msg = f"ENTRADA: {cantidad} pollos enteros agregados ({presas_a_sumar} presas)."
            if not add_history_db(log_msg, conn):
                # No lanzar error aquí, solo loggear advertencia si falla el historial
                 print("Advertencia: Fallo al guardar historial para add_pollos.")

            conn.commit() # Commit exitoso
            print(f"Inventario actualizado: Agregados {cantidad} pollos ({presas_a_sumar} presas).")
            return jsonify({"success": True, "message": f"{cantidad} pollos agregados."})

    except psycopg2.Error as e:
        print(f"Error de base de datos en add_pollos: {e}")
        conn.rollback() # Rollback en caso de error DB
        return jsonify({"success": False, "message": "Error al actualizar inventario (APo2)."}), 500
    except Exception as e:
        print(f"Error inesperado en add_pollos: {type(e).__name__} - {e}")
        conn.rollback() # Rollback en caso de error inesperado
        return jsonify({"success": False, "message": "Error inesperado del servidor (APo3)."}), 500
    finally:
        if conn:
            conn.close()
            print("Conexión a DB cerrada (add_pollos).")

@app.route('/api/add/presas_total', methods=['POST'])
def add_presas_total():
    # Similar a add_pollos, pero solo actualiza PRESAS_KEY
    req_data = request.get_json()
    cantidad = req_data.get('quantity')

    if not isinstance(cantidad, int) or cantidad <= 0:
        return jsonify({"success": False, "message": "Cantidad inválida."}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Error de conexión interna (APrT1)."}), 500

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
             cur.execute("""
                INSERT INTO inventory_info (key, value_int) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value_int = inventory_info.value_int + EXCLUDED.value_int;
             """, (PRESAS_KEY, cantidad))

             log_msg = f"ENTRADA: {cantidad} presas (generales) agregadas."
             if not add_history_db(log_msg, conn):
                 print("Advertencia: Fallo al guardar historial para add_presas_total.")

             conn.commit()
             print(f"Inventario actualizado: Agregadas {cantidad} presas generales.")
             return jsonify({"success": True, "message": f"{cantidad} presas agregadas."})

    except psycopg2.Error as e:
        print(f"Error de base de datos en add_presas_total: {e}")
        conn.rollback()
        return jsonify({"success": False, "message": "Error al actualizar inventario (APrT2)."}), 500
    except Exception as e:
        print(f"Error inesperado en add_presas_total: {type(e).__name__} - {e}")
        conn.rollback()
        return jsonify({"success": False, "message": "Error inesperado del servidor (APrT3)."}), 500
    finally:
        if conn:
            conn.close()
            print("Conexión a DB cerrada (add_presas_total).")

@app.route('/api/add/producto', methods=['POST'])
def add_producto():
    # Similar, actualiza o inserta producto
    req_data = request.get_json()
    nombre = req_data.get('name', '').strip().capitalize() # Normalizar nombre
    cantidad = req_data.get('quantity')
    precio_str = req_data.get('price')

    if not nombre or not isinstance(cantidad, int) or cantidad <= 0:
        return jsonify({"success": False, "message": "Nombre o cantidad inválidos."}), 400

    # Validar precio
    precio = Decimal('0.00')
    if precio_str is not None:
        try:
            precio_decimal = Decimal(str(precio_str))
            if precio_decimal >= 0:
                precio = precio_decimal.quantize(Decimal("0.01")) # Redondear a 2 decimales
            else:
                return jsonify({"success": False, "message": "El precio no puede ser negativo."}), 400
        except InvalidOperation:
            return jsonify({"success": False, "message": "Formato de precio inválido."}), 400
    # Si precio_str es None, se usa el default 0.00, lo cual podría ser intencional

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Error de conexión interna (APd1)."}), 500

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Usar INSERT ... ON CONFLICT para añadir o sumar cantidad y actualizar precio
            cur.execute("""
                INSERT INTO inventory_productos (nombre_producto, cantidad, precio)
                VALUES (%s, %s, %s)
                ON CONFLICT (nombre_producto)
                DO UPDATE SET
                    cantidad = inventory_productos.cantidad + EXCLUDED.cantidad,
                    precio = EXCLUDED.precio
                RETURNING cantidad;
            """, (nombre, cantidad, precio))

            result = cur.fetchone()
            stock_actual = result['cantidad'] if result else 'N/A'

            log_msg = f"ENTRADA PRODUCTO: {cantidad} {nombre} (Precio: {precio}, Stock ahora: {stock_actual})."
            if not add_history_db(log_msg, conn):
                print(f"Advertencia: Fallo al guardar historial para add_producto '{nombre}'.")

            conn.commit()
            print(f"Inventario actualizado: Producto '{nombre}' cantidad +{cantidad}, precio={precio}.")
            return jsonify({"success": True, "message": f"{cantidad} '{nombre}' agregados/actualizados."})

    except psycopg2.Error as e:
        print(f"Error de base de datos en add_producto para '{nombre}': {e}")
        conn.rollback()
        return jsonify({"success": False, "message": "Error al actualizar producto (APd2)."}), 500
    except Exception as e:
        print(f"Error inesperado en add_producto para '{nombre}': {type(e).__name__} - {e}")
        conn.rollback()
        return jsonify({"success": False, "message": "Error inesperado del servidor (APd3)."}), 500
    finally:
        if conn:
            conn.close()
            print(f"Conexión a DB cerrada (add_producto {nombre}).")


# --- RUTA DE VENTA (SELL) - CON LOGGING DETALLADO ---
@app.route('/api/sell', methods=['POST'])
def sell_cart():
    print("\n--- Iniciando procesamiento de venta ---")
    req_data = request.get_json()
    cart = req_data.get('cart')
    informar_cocinero = req_data.get('informar_cocinero', False)
    nota_cocinero = req_data.get('nota_cocinero', None)

    # Limpiar nota si es solo espacios en blanco
    if isinstance(nota_cocinero, str):
        nota_cocinero = nota_cocinero.strip()
        if not nota_cocinero:
            nota_cocinero = None

    if not isinstance(cart, list) or not cart:
        print("Error: Carrito inválido o vacío recibido.")
        return jsonify({"success": False, "message": "Carrito inválido o vacío."}), 400

    print(f"Carrito recibido: {len(cart)} items. Informar cocina: {informar_cocinero}. Nota: '{nota_cocinero}'")

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Error de conexión interna (S1)."}), 500

    total_venta = Decimal('0.00')
    items_para_db = []
    requerimientos = {"presas_total": 0, "productos": {}}
    items_faltantes = []
    stock_suficiente = True
    sale_id = None # Inicializar sale_id

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            print("Obteniendo definiciones y estado actual del inventario CON BLOQUEO (FOR UPDATE)...")
            # 1. Obtener definiciones (combos, presas por pollo)
            cur.execute("SELECT key, value FROM definitions WHERE key IN (%s, %s)", (COMBOS_KEY, PRESAS_PER_POLLO_KEY))
            definitions = {row['key']: row['value'] for row in cur.fetchall()}
            combos_def_json = definitions.get(COMBOS_KEY, {})
            # presas_pp = definitions.get(PRESAS_PER_POLLO_KEY, 8) # No se usa directamente aquí

            # 2. Obtener estado actual de inventario CON BLOQUEO
            cur.execute("SELECT key, value_int, value_numeric FROM inventory_info WHERE key IN (%s, %s) FOR UPDATE",
                        (PRESAS_KEY, PRESA_PRICE_KEY))
            info_data = {row['key']: row['value_int'] if row['value_int'] is not None else Decimal(row['value_numeric'])
                         for row in cur.fetchall()}
            current_presas_total = info_data.get(PRESAS_KEY, 0)
            presa_precio_default = info_data.get(PRESA_PRICE_KEY, DEFAULT_PRESA_PRICE)

            cur.execute("SELECT nombre_producto, cantidad, precio FROM inventory_productos FOR UPDATE")
            current_productos = {row['nombre_producto']: {"cantidad": row['cantidad'], "precio": Decimal(row['precio'])}
                                 for row in cur.fetchall()}
            print(f"Inventario actual bloqueado: Presas={current_presas_total}, PrecioPresa={presa_precio_default}")
            # print(f"Productos actuales bloqueados: {current_productos}") # Muy verboso

            print("Calculando requerimientos y total de la venta...")
            # 3. Calcular requerimientos y total
            for item_index, item in enumerate(cart):
                tipo = item.get('tipo')
                nombre = item.get('nombre')
                cantidad = item.get('quantity') # Frontend debe asegurar que sea int > 0
                display_name = item.get('display', nombre) # Nombre para mostrar
                precio_unitario = Decimal('0.00')

                print(f"  Procesando item {item_index+1}/{len(cart)}: {cantidad} x '{nombre}' (Tipo: {tipo}, Display: '{display_name}')")

                if not isinstance(cantidad, int) or cantidad <= 0:
                    print(f"    Error: Cantidad inválida ({cantidad}) para item '{nombre}'. Saltando item.")
                    items_faltantes.append(f"Cantidad inválida para '{display_name}'")
                    stock_suficiente = False
                    continue # Saltar al siguiente item del carrito

                if tipo == 'combo':
                    if nombre not in combos_def_json:
                        print(f"    Error: Combo '{nombre}' no encontrado en definiciones.")
                        items_faltantes.append(f"Combo '{display_name}' no definido")
                        stock_suficiente = False
                        continue
                    combo_info = combos_def_json[nombre]
                    if not isinstance(combo_info, dict):
                         print(f"    Error: Definición del combo '{nombre}' no es un diccionario.")
                         items_faltantes.append(f"Definición inválida para '{display_name}'")
                         stock_suficiente = False
                         continue

                    try:
                        precio_str = combo_info.get('precio', '0.00')
                        precio_unitario = Decimal(str(precio_str)).quantize(Decimal("0.01"))
                        if precio_unitario < 0: raise InvalidOperation("Precio negativo")
                        print(f"    Precio unitario combo: {precio_unitario}")
                    except InvalidOperation:
                        print(f"    Advertencia: Precio inválido ('{precio_str}') para combo '{nombre}'. Usando 0.00.")
                        precio_unitario = Decimal('0.00') # Usar 0 si el precio está mal formado

                    presas_req_combo = int(combo_info.get('presas_necesarias', 0)) * cantidad
                    requerimientos['presas_total'] += presas_req_combo
                    print(f"    Requiere {presas_req_combo} presas.")

                    productos_req_combo = combo_info.get('productos', {})
                    if isinstance(productos_req_combo, dict):
                        for p_combo, c_req_unitario in productos_req_combo.items():
                            c_req_total = int(c_req_unitario) * cantidad
                            requerimientos['productos'][p_combo] = requerimientos['productos'].get(p_combo, 0) + c_req_total
                            print(f"    Requiere {c_req_total} x '{p_combo}'.")
                    else:
                         print(f"    Advertencia: 'productos' en combo '{nombre}' no es un diccionario.")

                elif tipo == 'presa':
                    precio_unitario = presa_precio_default.quantize(Decimal("0.01"))
                    requerimientos['presas_total'] += cantidad
                    print(f"    Requiere {cantidad} presas (generales). Precio unitario: {precio_unitario}")

                elif tipo == 'producto':
                    if nombre not in current_productos:
                        print(f"    Error: Producto '{nombre}' no encontrado en inventario.")
                        items_faltantes.append(f"Producto '{display_name}' no existe")
                        stock_suficiente = False
                        continue
                    try:
                        precio_unitario = current_productos[nombre]['precio'].quantize(Decimal("0.01"))
                        print(f"    Precio unitario producto: {precio_unitario}")
                    except KeyError:
                         print(f"    Error: No se pudo obtener precio para producto '{nombre}'. Usando 0.00")
                         precio_unitario = Decimal('0.00')

                    requerimientos['productos'][nombre] = requerimientos['productos'].get(nombre, 0) + cantidad
                    print(f"    Requiere {cantidad} x '{nombre}'.")

                else:
                    print(f"    Error: Tipo de item desconocido '{tipo}' para '{nombre}'.")
                    items_faltantes.append(f"Tipo desconocido '{display_name}'")
                    stock_suficiente = False
                    continue # Saltar item desconocido

                # Añadir al total y a la lista para DB (solo si no hubo error con este item)
                item_total = precio_unitario * cantidad
                total_venta += item_total
                items_para_db.append({
                    "type": tipo,
                    "name": nombre,
                    "display": display_name,
                    "quantity": cantidad,
                    "price": float(precio_unitario) # Convertir a float para JSON/historial
                })
                print(f"    Subtotal item: {item_total:.2f}. Total acumulado: {total_venta:.2f}")

            print(f"\nRequerimientos totales calculados: Presas={requerimientos['presas_total']}, Productos={requerimientos['productos']}")
            print(f"Total Venta Calculado: {total_venta:.2f}")

            # 4. Verificar Stock Globalmente
            print("Verificando stock suficiente...")
            if current_presas_total < requerimientos['presas_total']:
                stock_suficiente = False
                items_faltantes.append(f"Presas (Req: {requerimientos['presas_total']} / Disp: {current_presas_total})")
                print(f"  Faltan presas: Req={requerimientos['presas_total']}, Disp={current_presas_total}")

            for p_req, c_req in requerimientos['productos'].items():
                 stock_disponible_prod = current_productos.get(p_req, {}).get('cantidad', 0)
                 if stock_disponible_prod < c_req:
                     stock_suficiente = False
                     items_faltantes.append(f"{p_req} (Req: {c_req} / Disp: {stock_disponible_prod})")
                     print(f"  Falta producto '{p_req}': Req={c_req}, Disp={stock_disponible_prod}")

            # 5. Si no hay stock, rollback y salir
            if not stock_suficiente:
                error_msg = f"Stock insuficiente: {', '.join(items_faltantes)}"
                print(f"Error final: {error_msg}")
                conn.rollback() # ¡Importante hacer rollback!
                print("ROLLBACK realizado por stock insuficiente.")
                return jsonify({"success": False, "message": error_msg}), 400

            # --- Si hay stock, proceder con la venta ---
            print("Stock suficiente. Procediendo a registrar venta y descontar inventario...")

            # 6. Insertar Venta Principal
            cur.execute("INSERT INTO sales (total_amount) VALUES (%s) RETURNING sale_id;", (total_venta,))
            sale_id = cur.fetchone()['sale_id']
            print(f"Venta registrada en tabla 'sales' con ID: {sale_id}, Total: {total_venta:.2f}")

            # 7. Insertar Items de la Venta
            if items_para_db: # Asegurarse de que hay items válidos
                items_sql_data = [(sale_id, i['type'], i['name'], i['display'], i['quantity'], Decimal(str(i['price'])))
                                  for i in items_para_db]
                cur.executemany("""
                    INSERT INTO sale_items (sale_id, item_type, item_name, display_name, quantity, price_per_item)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, items_sql_data)
                print(f"Items registrados en tabla 'sale_items' para venta ID: {sale_id}")
            else:
                print("Advertencia: No hay items válidos para registrar en 'sale_items', aunque la venta se creó.")


            # 8. Descontar Inventario - PRESAS
            if requerimientos['presas_total'] > 0:
                print(f"Intentando descontar {requerimientos['presas_total']} presas...")
                cur.execute("""
                    UPDATE inventory_info SET value_int = value_int - %s
                    WHERE key = %s AND value_int >= %s
                """, (requerimientos['presas_total'], PRESAS_KEY, requerimientos['presas_total']))
                if cur.rowcount == 0:
                    # Esto no debería pasar si el FOR UPDATE y la verificación funcionaron, pero es una salvaguarda
                    print("¡ERROR CRÍTICO! Fallo al descontar presas (rowcount 0). Revisar concurrencia o lógica.")
                    raise psycopg2.Error("Fallo al descontar presas después de la verificación.")
                print("Presas descontadas OK.")
            else:
                print("No se requieren presas, no se descuenta.")

            # 9. Descontar Inventario - PRODUCTOS
            if requerimientos['productos']:
                print("Intentando descontar productos...")
                for p_desc, c_desc in requerimientos['productos'].items():
                    print(f"  Descontando {c_desc} x '{p_desc}'...")
                    cur.execute("""
                        UPDATE inventory_productos SET cantidad = cantidad - %s
                        WHERE nombre_producto = %s AND cantidad >= %s
                    """, (c_desc, p_desc, c_desc))
                    if cur.rowcount == 0:
                        stock_actual_fallo = current_productos.get(p_desc, {}).get('cantidad', '???')
                        print(f"¡ERROR CRÍTICO! Fallo al descontar producto '{p_desc}' (rowcount 0). Stock actual era {stock_actual_fallo}. Req: {c_desc}.")
                        raise psycopg2.Error(f"Fallo al descontar producto '{p_desc}' después de la verificación.")
                    print(f"  Producto '{p_desc}' descontado OK.")
                print("Productos descontados OK.")
            else:
                print("No se requieren productos, no se descuenta.")

            # 10. Enviar a Cocina si aplica
            if informar_cocinero:
                print("Enviando orden a cocina...")
                # Usar items_para_db que ya tiene precios como float
                items_json_cocina = json.dumps(items_para_db)
                try:
                    cur.execute("INSERT INTO pending_orders (items, nota) VALUES (%s, %s) RETURNING order_id;",
                                (items_json_cocina, nota_cocinero))
                    order_id_cocina = cur.fetchone()['order_id']
                    print(f"Orden enviada a cocina OK. ID de orden pendiente: {order_id_cocina}")
                except psycopg2.Error as e_cocina:
                    # Decidir si fallar toda la venta o solo loggear el error de cocina
                    print(f"¡ERROR al enviar a cocina! Orden ID {sale_id}. Error: {e_cocina}. LA VENTA CONTINUARÁ.")
                    # Podrías lanzar un error aquí si es crítico: raise psycopg2.Error("Fallo al enviar a cocina")
            else:
                print("No se requiere informar a cocina.")

            # 11. Registrar en Historial (último paso antes de commit)
            resumen_display = ', '.join([f"{item.get('quantity', '?')}x{item.get('display', item.get('name', '?'))}"
                                         for item in items_para_db])
            total_venta_str = f"{total_venta:.2f}"
            log_msg = f"VENTA CARRITO (ID:{sale_id}, {len(items_para_db)} items válidos): {resumen_display}. Total: ${total_venta_str}"
            if informar_cocinero: log_msg += " [Enviado a Cocina]"
            if nota_cocinero: log_msg += f" [Nota: {nota_cocinero[:30]}{'...' if len(nota_cocinero)>30 else ''}]"

            if not add_history_db(log_msg, conn):
                 # Solo loggear, no fallar la venta por esto
                 print(f"Advertencia: Fallo al guardar historial para venta ID {sale_id}.")

            # 12. COMMIT FINAL
            conn.commit()
            print(f"--- Venta ID {sale_id} COMPLETADA Y GUARDADA (COMMIT) ---")
            return jsonify({"success": True, "message": "Venta procesada exitosamente!"})

    except psycopg2.Error as e:
        error_type = type(e).__name__
        error_msg_db = f"Error de Base de Datos durante venta (ID: {sale_id if sale_id else 'PRE-ID'}): {error_type} - {e}"
        print(error_msg_db)
        conn.rollback() # Asegurar rollback en error DB
        print("ROLLBACK realizado por error de base de datos.")
        # Devolver un mensaje genérico al frontend por seguridad
        return jsonify({"success": False, "message": f"Error interno del servidor al procesar la venta ({error_type})."}), 500
    except (InvalidOperation, ValueError, TypeError, KeyError) as e:
        error_type = type(e).__name__
        error_msg_val = f"Error de datos/validación durante venta (ID: {sale_id if sale_id else 'PRE-ID'}): {error_type} - {e}"
        print(error_msg_val)
        conn.rollback() # Asegurar rollback
        print("ROLLBACK realizado por error de datos/validación.")
        return jsonify({"success": False, "message": f"Error en los datos del carrito o definiciones ({error_type})."}), 400 # 400 Bad Request
    except Exception as e: # Capturar cualquier otro error inesperado
        error_type = type(e).__name__
        error_msg_ines = f"Error inesperado durante venta (ID: {sale_id if sale_id else 'PRE-ID'}): {error_type} - {e}"
        print(error_msg_ines)
        conn.rollback() # Asegurar rollback
        print("ROLLBACK realizado por error inesperado.")
        return jsonify({"success": False, "message": "Error inesperado del servidor durante la venta."}), 500
    finally:
        if conn:
            conn.close()
            print(f"Conexión a DB cerrada (sell_cart, ID: {sale_id if sale_id else 'N/A'}).")


# --- Rutas REMOVE, REPORTS, UPDATE PRICE, CUSTOM COMBOS, ORDERS (sin cambios mayores) ---
# (Incluye el código de las otras rutas aquí, similar a como estaba antes)
# ... (Código de /api/remove/* , /api/reports/sales, /api/update/price, etc.) ...
# Asegúrate de incluir todas las demás rutas que tenías

# --- Ejecutar la Aplicación ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000)) # Usar PORT de Railway o default 5000
    print(f"Iniciando servidor Flask en MODO DEBUG LOCAL (o producción si PORT está definido)...")
    # debug=True es útil localmente, pero desactívalo en producción real por seguridad y rendimiento
    # Railway generalmente maneja el modo de ejecución a través de Gunicorn/variables de entorno
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'False') == 'True')
