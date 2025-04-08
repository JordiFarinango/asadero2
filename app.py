# app.py - Backend con Flask y Hashing

import os
import json
import datetime
from flask import Flask, render_template, request, jsonify
# --- CAMBIO: Importar funciones de hashing ---
from werkzeug.security import generate_password_hash, check_password_hash

# --- Configuración Inicial ---
app = Flask(__name__)
DATA_FILE = 'data.json'

# --- Funciones para Manejar Datos (data.json) ---

def load_data():
    """Carga los datos desde el archivo data.json."""
    if not os.path.exists(DATA_FILE):
        print(f"Archivo '{DATA_FILE}' no encontrado. Creando uno nuevo con hashes.")
        initial_data = {
            "users": {
                # --- CAMBIO: Guardar hashes en lugar de texto plano ---
                "admin": {
                    # Hash para "admin123" (ejemplo, puede variar)
                    "password_hash": generate_password_hash("admin123"),
                    "role": "admin"
                    },
                "venta": {
                    # Hash para "venta123" (ejemplo, puede variar)
                    "password_hash": generate_password_hash("venta123"),
                    "role": "vendedor"
                    }
            },
            "inventory": {
                "pollosEnteros": 0,
                "presas": { "pechuga": 0, "muslo": 0, "ala": 0, "pierna": 0 },
                "productos": {}
            },
            "history": [f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Sistema inicializado."],
            "presasPorPollo": {
                 "pechuga": 2, "muslo": 2, "ala": 2, "pierna": 2
             },
            "combos": {
                "combo_1_8_pechuga": { "pechuga": 1 }, "combo_1_8_muslo": { "muslo": 1 },
                "combo_1_8_ala": { "ala": 1 }, "combo_1_8_pierna": { "pierna": 1 },
                "combo_1_4_pechuga_ala": { "pechuga": 1, "ala": 1 }, "combo_1_4_muslo_pierna": { "muslo": 1, "pierna": 1 },
                "combo_1_2": { "pechuga": 1, "ala": 1, "muslo": 1, "pierna": 1 },
                "combo_entero": { "pechuga": 2, "ala": 2, "muslo": 2, "pierna": 2 }
            }
        }
        save_data(initial_data)
        return initial_data
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Asegurar estructura mínima
            data.setdefault('users', {})
            inv = data.setdefault('inventory', {"pollosEnteros": 0, "presas": {}, "productos": {}})
            inv.setdefault('pollosEnteros', 0); inv.setdefault('presas', {}); inv.setdefault('productos', {})
            data.setdefault('history', [])
            data.setdefault('presasPorPollo', {"pechuga": 2, "muslo": 2, "ala": 2, "pierna": 2})
            data.setdefault('combos', {})
            # Asegurar que los usuarios tengan 'password_hash'
            for user_data in data['users'].values():
                user_data.setdefault('password_hash', None) # O un hash por defecto inválido
                user_data.setdefault('role', 'vendedor')
            return data
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error crítico cargando {DATA_FILE}: {e}. Se usarán datos por defecto.")
        return {
            "users": {}, "inventory": {"pollosEnteros": 0, "presas": {}, "productos": {}},
            "history": [], "presasPorPollo": {"pechuga": 2, "muslo": 2, "ala": 2, "pierna": 2}, "combos": {}
        }

def save_data(data):
    """Guarda los datos proporcionados en el archivo data.json."""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except IOError as e:
        print(f"Error crítico guardando en {DATA_FILE}: {e}")

def add_history_log(message):
    """Agrega una entrada al historial con timestamp y guarda los datos."""
    data = load_data()
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data['history'].insert(0, f"[{timestamp}] {message}")
    MAX_HISTORY = 100
    if len(data['history']) > MAX_HISTORY:
        data['history'] = data['history'][:MAX_HISTORY]
    save_data(data)


# --- Rutas de la Aplicación ---

@app.route('/')
def index():
    """Sirve la página principal HTML (frontend)."""
    return render_template('index.html')

# --- Rutas de la API ---

@app.route('/login', methods=['POST'])
def login():
    """Maneja las solicitudes de inicio de sesión usando hashes."""
    data = load_data()
    users = data.get('users', {})
    req_data = request.get_json()

    if not req_data or 'username' not in req_data or 'password' not in req_data:
        return jsonify({"success": False, "message": "Faltan datos."}), 400

    username = req_data['username']
    password_attempt = req_data['password'] # Contraseña ingresada por el usuario
    user_info = users.get(username)

    # --- CAMBIO: Usar check_password_hash para comparar ---
    if user_info and 'password_hash' in user_info and \
       check_password_hash(user_info['password_hash'], password_attempt):
        # El hash guardado coincide con la contraseña ingresada
        print(f"Login exitoso (hash check): {username}")
        return jsonify({"success": True, "role": user_info.get('role', 'vendedor')})
    else:
        # Usuario no encontrado o la contraseña no coincide con el hash
        print(f"Login fallido (hash check): {username}")
        return jsonify({"success": False, "message": "Credenciales incorrectas."}), 401

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    """Devuelve el estado actual del inventario y definiciones."""
    data = load_data()
    inventory_data = {
        "inventory": data.get('inventory', {"pollosEnteros": 0, "presas": {}, "productos": {}}),
        "combos": data.get('combos', {}),
        "presasPorPollo": data.get('presasPorPollo', {})
    }
    return jsonify(inventory_data)

@app.route('/api/history', methods=['GET'])
def get_history():
    """Devuelve las últimas entradas del historial."""
    data = load_data()
    return jsonify({"history": data.get('history', [])})

# --- RUTAS PARA AGREGAR INVENTARIO ---
@app.route('/api/add/pollos', methods=['POST'])
def add_pollos():
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400
    data = load_data(); inventory = data['inventory']; presas_por_pollo = data.get('presasPorPollo', {})
    inventory['pollosEnteros'] = inventory.get('pollosEnteros', 0) + cantidad
    for presa, cant_pp in presas_por_pollo.items(): inventory['presas'][presa] = inventory['presas'].get(presa, 0) + cantidad * cant_pp
    add_history_log(f"ENTRADA: {cantidad} pollos enteros."); print(f"Agregados {cantidad} pollos.")
    return jsonify({"success": True, "message": f"{cantidad} pollos agregados."})

@app.route('/api/add/presas', methods=['POST'])
def add_presas():
    req_data = request.get_json(); tipo_presa = req_data.get('type', '').lower(); cantidad = req_data.get('quantity')
    if not tipo_presa or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400
    data = load_data()
    if tipo_presa not in data.get('presasPorPollo', {}): return jsonify({"success": False, "message": f"Tipo '{tipo_presa}' inválido."}), 400
    inventory = data['inventory']
    inventory['presas'][tipo_presa] = inventory['presas'].get(tipo_presa, 0) + cantidad
    add_history_log(f"ENTRADA: {cantidad} {tipo_presa}(s)."); print(f"Agregadas {cantidad} {tipo_presa}(s).")
    return jsonify({"success": True, "message": f"{cantidad} {tipo_presa}(s) agregados."})

@app.route('/api/add/producto', methods=['POST'])
def add_producto():
    req_data = request.get_json(); nombre_producto = req_data.get('name', '').strip().capitalize(); cantidad = req_data.get('quantity')
    if not nombre_producto or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400
    data = load_data(); inventory = data['inventory']
    inventory['productos'][nombre_producto] = inventory['productos'].get(nombre_producto, 0) + cantidad
    stock = inventory['productos'][nombre_producto]
    add_history_log(f"ENTRADA PRODUCTO: {cantidad} {nombre_producto} (Stock: {stock})."); print(f"Producto: {cantidad} x {nombre_producto}")
    return jsonify({"success": True, "message": f"{cantidad} '{nombre_producto}' agregados."})

# --- RUTAS PARA VENDER Y ELIMINAR ---
@app.route('/api/sell', methods=['POST'])
def sell_cart():
    req_data = request.get_json(); cart = req_data.get('cart')
    if not isinstance(cart, list) or not cart: return jsonify({"success": False, "message": "Carrito inválido."}), 400
    data = load_data(); inventory = data['inventory']; combos_def = data.get('combos', {}); current_presas = inventory.get('presas', {}); current_productos = inventory.get('productos', {})
    requerimientos = {"presas": {}, "productos": {}}; items_faltantes = []; stock_suficiente = True
    for item in cart:
        tipo = item.get('tipo'); nombre = item.get('nombre'); cantidad = item.get('cantidad', 0); display_name = item.get('display', nombre)
        if cantidad <= 0: continue
        if tipo == 'combo':
            if nombre not in combos_def: stock_suficiente = False; items_faltantes.append(f"Combo '{display_name}'? "); continue
            for presa, cant_req in combos_def[nombre].items(): requerimientos['presas'][presa] = requerimientos['presas'].get(presa, 0) + cant_req * cantidad
        elif tipo == 'presa': requerimientos['presas'][nombre] = requerimientos['presas'].get(nombre, 0) + cantidad
        elif tipo == 'producto': requerimientos['productos'][nombre] = requerimientos['productos'].get(nombre, 0) + cantidad
        else: stock_suficiente = False; items_faltantes.append(f"Tipo? '{display_name}'")
    for presa, cant_req in requerimientos['presas'].items():
        if current_presas.get(presa, 0) < cant_req: stock_suficiente = False; items_faltantes.append(f"{presa}({cant_req}/{current_presas.get(presa, 0)})")
    for producto, cant_req in requerimientos['productos'].items():
         if current_productos.get(producto, 0) < cant_req: stock_suficiente = False; items_faltantes.append(f"{producto}({cant_req}/{current_productos.get(producto, 0)})")
    if not stock_suficiente: print(f"Venta fallida stock: {items_faltantes}"); return jsonify({"success": False, "message": f"Stock insuficiente: {', '.join(items_faltantes)}"}), 400
    for presa, cant_req in requerimientos['presas'].items(): inventory['presas'][presa] -= cant_req
    for producto, cant_req in requerimientos['productos'].items(): inventory['productos'][producto] -= cant_req
    resumen_display = ', '.join([f"{item['cantidad']}x{item.get('display', item['nombre'])}" for item in cart])
    add_history_log(f"VENTA CARRITO ({len(cart)} items): {resumen_display}.")
    print(f"Venta procesada: {resumen_display}")
    return jsonify({"success": True, "message": "Venta procesada!"})

@app.route('/api/remove/pollos', methods=['POST'])
def remove_pollos():
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400
    data = load_data(); inventory = data['inventory']; presas_por_pollo = data.get('presasPorPollo', {}); current_presas = inventory.get('presas', {})
    presas_necesarias = {}; stock_presas_suficiente = True
    for presa, cant_pp in presas_por_pollo.items():
        req = cantidad * cant_pp
        if current_presas.get(presa, 0) < req: stock_presas_suficiente = False; presas_necesarias[presa] = f"Req:{req}/Disp:{current_presas.get(presa, 0)}"
    if not stock_presas_suficiente: msg = f"Presas insuficientes: {presas_necesarias}"; print(msg); return jsonify({"success": False, "message": msg}), 400
    inventory['pollosEnteros'] = max(0, inventory.get('pollosEnteros', 0) - cantidad)
    for presa, cant_pp in presas_por_pollo.items(): inventory['presas'][presa] = max(0, inventory['presas'].get(presa, 0) - cantidad * cant_pp)
    add_history_log(f"ELIMINACIÓN: {cantidad} pollos (merma)."); print(f"Eliminados {cantidad} pollos (merma).")
    return jsonify({"success": True, "message": f"{cantidad} pollos eliminados." })

@app.route('/api/remove/presas', methods=['POST'])
def remove_presas():
    req_data = request.get_json(); tipo_presa = req_data.get('type', '').lower(); cantidad = req_data.get('quantity')
    if not tipo_presa or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400
    data = load_data(); inventory = data['inventory']
    if tipo_presa not in inventory.get('presas', {}): return jsonify({"success": False, "message": f"Presa '{tipo_presa}' no existe."}), 400
    if inventory['presas'][tipo_presa] < cantidad: msg = f"Stock insuf. {tipo_presa} (Disp:{inventory['presas'][tipo_presa]})"; return jsonify({"success": False, "message": msg}), 400
    inventory['presas'][tipo_presa] -= cantidad
    add_history_log(f"ELIMINACIÓN: {cantidad} {tipo_presa}(s) (merma)."); print(f"Eliminadas {cantidad} {tipo_presa}(s) (merma).")
    return jsonify({"success": True, "message": f"{cantidad} {tipo_presa}(s) eliminados." })

@app.route('/api/remove/producto', methods=['POST'])
def remove_producto():
    req_data = request.get_json(); nombre_producto = req_data.get('name', '').strip().capitalize(); cantidad = req_data.get('quantity')
    if not nombre_producto or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400
    data = load_data(); inventory = data['inventory']
    if nombre_producto not in inventory.get('productos', {}): return jsonify({"success": False, "message": f"Producto '{nombre_producto}' no existe."}), 400
    if inventory['productos'][nombre_producto] < cantidad: msg = f"Stock insuf. {nombre_producto} (Disp:{inventory['productos'][nombre_producto]})"; return jsonify({"success": False, "message": msg}), 400
    inventory['productos'][nombre_producto] -= cantidad
    stock_restante = inventory['productos'][nombre_producto]
    add_history_log(f"ELIMINACIÓN PRODUCTO: {cantidad} {nombre_producto} (merma). Stock: {stock_restante}."); print(f"Eliminado producto: {cantidad} x {nombre_producto} (merma).")
    return jsonify({"success": True, "message": f"{cantidad} '{nombre_producto}' eliminados." })


# --- Ejecutar la Aplicación ---
if __name__ == '__main__':
    print("Iniciando servidor Flask...")
    # Instalar Werkzeug si da error de importación: pip install Werkzeug
    app.run(host='0.0.0.0', port=5000, debug=True)
