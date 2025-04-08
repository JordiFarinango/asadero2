# app.py - Backend con Flask, PostgreSQL y Registro de Ventas

import os
import json
import datetime
import psycopg2 # Librería para PostgreSQL
import psycopg2.extras # Para usar diccionarios en resultados
from decimal import Decimal, InvalidOperation # Para manejar precios con precisión
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# --- Configuración Inicial ---
app = Flask(__name__)
# Leer la URL de la base de datos desde las variables de entorno (Railway la inyecta)
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print("¡ERROR FATAL! Variable de entorno DATABASE_URL no encontrada.")
    # Considera detener la app si no hay DB URL en producción
    # exit()

# Configurar CORS - Permitir todos los orígenes por ahora (*)
# En producción, reemplazar '*' con la URL de Netlify: "https://tu-sitio.netlify.app"
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Conexión a Base de Datos ---

def get_db_connection():
    """Establece conexión con la base de datos PostgreSQL."""
    if not DATABASE_URL:
        print("Intento de conexión DB fallido: DATABASE_URL no configurada.")
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        # print("Conexión a DB establecida.") # Opcional: loguear conexión exitosa
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
            # Crear tabla de usuarios
            print("Verificando tabla 'users'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username VARCHAR(80) PRIMARY KEY,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(50) NOT NULL
                );
            """)
            # Crear tabla de presas
            print("Verificando tabla 'inventory_presas'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_presas (
                    nombre_presa VARCHAR(80) PRIMARY KEY,
                    cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0)
                );
            """)
            # Crear tabla de productos (con precio)
            print("Verificando tabla 'inventory_productos'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_productos (
                    nombre_producto VARCHAR(100) PRIMARY KEY,
                    cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0),
                    precio NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (precio >= 0.00)
                );
            """)
            # Asegurar que columna precio exista (migración simple)
            cur.execute("""
                ALTER TABLE inventory_productos ADD COLUMN IF NOT EXISTS precio NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (precio >= 0.00);
            """)
            # Crear tabla de info (pollos enteros)
            print("Verificando tabla 'inventory_info'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_info (
                    key VARCHAR(50) PRIMARY KEY,
                    value INTEGER NOT NULL DEFAULT 0
                );
            """)
            # Crear tabla de historial simple (mensajes)
            print("Verificando tabla 'history'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    message TEXT NOT NULL
                );
            """)
            # Crear tabla de definiciones (combos, presas por pollo)
            print("Verificando tabla 'definitions'...")
            cur.execute("""
                 CREATE TABLE IF NOT EXISTS definitions (
                     key VARCHAR(50) PRIMARY KEY,
                     value JSONB NOT NULL
                 );
             """)
            # --- NUEVAS TABLAS PARA VENTAS/REPORTES ---
            print("Verificando tabla 'sales'...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sales (
                    sale_id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    total_amount NUMERIC(10, 2) NOT NULL CHECK (total_amount >= 0.00)
                );
            """)
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
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_sale_items_sale_id ON sale_items (sale_id);
            """)

            # --- Insertar/Actualizar datos iniciales ---
            # (Omitido por brevedad - Asegúrate de tener esta lógica de la versión anterior si quieres datos iniciales)
            # Ejemplo: Insertar usuarios si no existen, presas base, productos con precio, definiciones...

            conn.commit()
            print("Base de datos inicializada/actualizada.")
    except psycopg2.Error as e:
        print(f"Error durante inicialización/actualización de DB: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

# Llamar a init_db() una vez al inicio
# En producción real, se usarían herramientas de migración (ej: Alembic)
# Pero para esta app, llamarlo aquí asegura que las tablas existan.
with app.app_context():
    init_db()

# --- Funciones Auxiliares ---
def add_history_db(message, conn):
    """Agrega una entrada al historial simple en la base de datos."""
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO history (message) VALUES (%s)", (message,))
            # Limitar historial
            cur.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY timestamp DESC LIMIT 100);")
        return True
    except psycopg2.Error as e: print(f"Error añadiendo historial a DB: {e}"); return False

# --- Rutas API ---

@app.route('/')
def index(): return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    # ... (Sin cambios respecto a la versión anterior) ...
    req_data = request.get_json(); username = req_data.get('username'); password_attempt = req_data.get('password')
    if not username or not password_attempt: return jsonify({"success": False, "message": "Faltan datos."}), 400
    conn = get_db_connection(); user_info = None
    if not conn: return jsonify({"success": False, "message": "Error DB (L1)."}), 500
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT password_hash, role FROM users WHERE username = %s", (username,))
            user_info = cur.fetchone()
        if user_info and check_password_hash(user_info['password_hash'], password_attempt):
            print(f"Login OK: {username}"); return jsonify({"success": True, "role": user_info['role']})
        else:
            print(f"Login FAIL: {username}"); return jsonify({"success": False, "message": "Credenciales incorrectas."}), 401
    except psycopg2.Error as e: print(f"Error DB login: {e}"); return jsonify({"success": False, "message": "Error interno (L2)."}), 500
    finally:
        if conn: conn.close()


@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    # ... (Sin cambios respecto a la versión anterior) ...
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
                try: combos_con_precio_float[key] = { "presas": combo_data.get("presas", {}), "precio": float(combo_data.get("precio", "0.00")) }
                except (ValueError, TypeError): combos_con_precio_float[key] = { "presas": combo_data.get("presas", {}), "precio": 0.00 }
            inventory_data = { "inventory": {"pollosEnteros": pollos_enteros, "presas": presas, "productos": productos}, "combos": combos_con_precio_float, "presasPorPollo": definitions.get('presasPorPollo', {}) }
        return jsonify(inventory_data)
    except psycopg2.Error as e: print(f"Error DB get_inventory: {e}"); return jsonify({"success": False, "message": "Error interno (I2)."}), 500
    finally:
        if conn: conn.close()

@app.route('/api/history', methods=['GET'])
def get_history():
     # ... (Sin cambios respecto a la versión anterior) ...
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
    # ... (Sin cambios funcionales, solo usa la conexión transaccional) ...
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
    # ... (Sin cambios funcionales, solo usa la conexión transaccional) ...
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
    # ... (Sin cambios funcionales, solo usa la conexión transaccional) ...
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

# --- RUTA VENDER (Modificada para guardar en sales y sale_items) ---
@app.route('/api/sell', methods=['POST'])
def sell_cart():
    req_data = request.get_json(); cart = req_data.get('cart')
    if not isinstance(cart, list) or not cart: return jsonify({"success": False, "message": "Carrito inválido."}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Error DB (S1)."}), 500

    total_venta = Decimal('0.00')
    items_para_db = [] # Lista para guardar detalles para sale_items

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Cargar definiciones y stock actual DENTRO de la transacción
            cur.execute("SELECT value FROM definitions WHERE key = 'combos'")
            combos_def_json = cur.fetchone()['value'] if cur.rowcount > 0 else {}
            cur.execute("SELECT nombre_presa, cantidad FROM inventory_presas FOR UPDATE")
            current_presas = {row['nombre_presa']: row['cantidad'] for row in cur.fetchall()}
            cur.execute("SELECT nombre_producto, cantidad, precio FROM inventory_productos FOR UPDATE")
            current_productos = {row['nombre_producto']: {"cantidad": row['cantidad'], "precio": Decimal(row['precio'])} for row in cur.fetchall()}

            requerimientos = {"presas": {}, "productos": {}}; items_faltantes = []; stock_suficiente = True

            # Calcular requerimientos, total venta y preparar items para DB
            for item in cart:
                tipo = item.get('tipo'); nombre = item.get('nombre'); cantidad = item.get('cantidad', 0); display_name = item.get('display', nombre)
                precio_unitario = Decimal('0.00')
                if cantidad <= 0: continue

                if tipo == 'combo':
                    if nombre not in combos_def_json: stock_suficiente = False; items_faltantes.append(f"Combo '{display_name}'?"); continue
                    combo_info = combos_def_json[nombre]
                    try: precio_unitario = Decimal(str(combo_info.get('precio', '0.00')))
                    except InvalidOperation: print(f"Adv: Precio inválido combo {nombre}")
                    for p, cR in combo_info.get('presas', {}).items(): requerimientos['presas'][p] = requerimientos['presas'].get(p, 0) + cR * cantidad
                elif tipo == 'presa':
                    requerimientos['presas'][nombre] = requerimientos['presas'].get(nombre, 0) + cantidad
                    # Presas individuales no tienen precio asignado aquí
                elif tipo == 'producto':
                    if nombre not in current_productos: stock_suficiente = False; items_faltantes.append(f"Prod '{display_name}'?"); continue
                    precio_unitario = current_productos[nombre]['precio']
                    requerimientos['productos'][nombre] = requerimientos['productos'].get(nombre, 0) + cantidad
                else: stock_suficiente = False; items_faltantes.append(f"Tipo? '{display_name}'")

                total_venta += precio_unitario * cantidad
                # Añadir a la lista para insertar en sale_items
                items_para_db.append({
                    "type": tipo, "name": nombre, "display": display_name,
                    "quantity": cantidad, "price": precio_unitario
                })

            # Comprobar stock
            for p, cR in requerimientos['presas'].items():
                if current_presas.get(p, 0) < cR: stock_suficiente = False; items_faltantes.append(f"{p}({cR}/{current_presas.get(p, 0)})")
            for p, cR in requerimientos['productos'].items():
                 if current_productos.get(p, {}).get('cantidad', 0) < cR: stock_suficiente = False; items_faltantes.append(f"{p}({cR}/{current_productos.get(p, {}).get('cantidad', 0)})")

            if not stock_suficiente:
                print(f"Venta fallida stock: {items_faltantes}"); conn.rollback(); return jsonify({"success": False, "message": f"Stock insuficiente: {', '.join(items_faltantes)}"}), 400

            # --- Si hay stock, proceder ---
            print("Stock OK. Procesando venta en DB...")

            # 1. Insertar en la tabla 'sales' y obtener el ID de la venta
            cur.execute("INSERT INTO sales (total_amount) VALUES (%s) RETURNING sale_id;", (total_venta,))
            sale_id = cur.fetchone()['sale_id']
            print(f"Venta registrada con ID: {sale_id}, Total: {total_venta}")

            # 2. Insertar cada item vendido en 'sale_items'
            items_sql_data = []
            for item_info in items_para_db:
                items_sql_data.append((
                    sale_id, item_info['type'], item_info['name'], item_info['display'],
                    item_info['quantity'], item_info['price']
                ))
            cur.executemany("""
                INSERT INTO sale_items (sale_id, item_type, item_name, display_name, quantity, price_per_item)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, items_sql_data)
            print(f"Items de la venta {sale_id} registrados.")

            # 3. Descontar del inventario
            print("Descontando inventario...")
            for p, cR in requerimientos['presas'].items(): cur.execute("UPDATE inventory_presas SET cantidad = cantidad - %s WHERE nombre_presa = %s", (cR, p))
            for p, cR in requerimientos['productos'].items(): cur.execute("UPDATE inventory_productos SET cantidad = cantidad - %s WHERE nombre_producto = %s", (cR, p))
            print("Inventario descontado.")

            # 4. Añadir al historial simple (opcional, pero útil para vista rápida)
            resumen_display = ', '.join([f"{item['cantidad']}x{item.get('display', item['nombre'])}" for item in cart])
            total_venta_str = f"{total_venta:.2f}"
            log_msg = f"VENTA CARRITO (ID:{sale_id}, {len(cart)} items): {resumen_display}. Total: ${total_venta_str}"
            if not add_history_db(log_msg, conn): raise psycopg2.Error("Fallo al guardar historial simple")

            # 5. Confirmar transacción
            conn.commit()
            print(f"Venta {sale_id} confirmada y guardada.")
            return jsonify({"success": True, "message": "Venta procesada!"})

    except psycopg2.Error as e:
        print(f"Error DB sell_cart: {e}");
        if conn: conn.rollback() # Revertir TODO si algo falla
        return jsonify({"success": False, "message": "Error interno al vender (S2)."}), 500
    except InvalidOperation as e:
         print(f"Error de precio en venta: {e}");
         if conn: conn.rollback()
         return jsonify({"success": False, "message": "Error en formato de precio."}), 500
    finally:
        if conn: conn.close()


# --- RUTAS ELIMINAR (Sin cambios funcionales, solo usan la conexión transaccional) ---
@app.route('/api/remove/pollos', methods=['POST'])
def remove_pollos():
    # ... (lógica igual, asegurar que add_history_db y commit/rollback funcionen) ...
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
    # ... (lógica igual, asegurar que add_history_db y commit/rollback funcionen) ...
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
    # ... (lógica igual, asegurar que add_history_db y commit/rollback funcionen) ...
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

# --- Ejecutar la Aplicación (Solo para desarrollo local) ---
if __name__ == '__main__':
    print("Iniciando servidor Flask para DESARROLLO LOCAL...")
    app.run(host='0.0.0.0', port=5000, debug=True)

