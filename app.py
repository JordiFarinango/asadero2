# app.py - Backend con Flask y Debug para Venta

import os
import json
import datetime
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# --- Configuración Inicial ---
app = Flask(__name__)
DATA_FILE = 'data.json'
CORS(app, resources={r"/*": {"origins": "*"}}) # Permitir todo por ahora

# --- Funciones para Manejar Datos (data.json) ---
# (load_data, save_data sin cambios)
def load_data():
    if not os.path.exists(DATA_FILE):
        print(f"Archivo '{DATA_FILE}' no encontrado. Creando uno nuevo con hashes.")
        initial_data = {
            "users": {
                "admin": { "password_hash": generate_password_hash("admin123"), "role": "admin" },
                "venta": { "password_hash": generate_password_hash("venta123"), "role": "vendedor" }
            },
            "inventory": {"pollosEnteros": 0, "presas": {}, "productos": {}},
            "history": [f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Sistema inicializado."],
            "presasPorPollo": { "pechuga": 2, "muslo": 2, "ala": 2, "pierna": 2 },
            "combos": { "combo_1_8_pechuga": { "pechuga": 1 }, "combo_1_8_muslo": { "muslo": 1 }, "combo_1_8_ala": { "ala": 1 }, "combo_1_8_pierna": { "pierna": 1 }, "combo_1_4_pechuga_ala": { "pechuga": 1, "ala": 1 }, "combo_1_4_muslo_pierna": { "muslo": 1, "pierna": 1 }, "combo_1_2": { "pechuga": 1, "ala": 1, "muslo": 1, "pierna": 1 }, "combo_entero": { "pechuga": 2, "ala": 2, "muslo": 2, "pierna": 2 } }
        }
        save_data(initial_data); return initial_data
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
        data.setdefault('users', {}); inv = data.setdefault('inventory', {"pollosEnteros": 0, "presas": {}, "productos": {}})
        inv.setdefault('pollosEnteros', 0); inv.setdefault('presas', {}); inv.setdefault('productos', {})
        data.setdefault('history', []); data.setdefault('presasPorPollo', {"pechuga": 2, "muslo": 2, "ala": 2, "pierna": 2}); data.setdefault('combos', {})
        for user_data in data['users'].values(): user_data.setdefault('password_hash', None); user_data.setdefault('role', 'vendedor')
        return data
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error crítico cargando {DATA_FILE}: {e}. Usando datos por defecto."); return {"users": {}, "inventory": {"pollosEnteros": 0, "presas": {}, "productos": {}}, "history": [], "presasPorPollo": {"pechuga": 2, "muslo": 2, "ala": 2, "pierna": 2}, "combos": {}}

def save_data(data):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"Datos guardados exitosamente en {DATA_FILE}") # Log de guardado exitoso
    except IOError as e: print(f"Error crítico guardando en {DATA_FILE}: {e}")

def add_history_log(message):
    # Modificado para no cargar/guardar aquí, asume que 'data' se pasa o se carga/guarda fuera
    # Esta función ahora solo formatea el mensaje y lo añade a la lista 'history'
    # La responsabilidad de cargar/guardar recae en la función que llama a esta.
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return f"[{timestamp}] {message}"


# --- Rutas de la Aplicación ---
@app.route('/')
def index(): return render_template('index.html')

# --- Rutas de la API ---
@app.route('/login', methods=['POST'])
def login():
    data = load_data(); users = data.get('users', {}); req_data = request.get_json()
    if not req_data or 'username' not in req_data or 'password' not in req_data: return jsonify({"success": False, "message": "Faltan datos."}), 400
    username = req_data['username']; password_attempt = req_data['password']; user_info = users.get(username)
    if user_info and 'password_hash' in user_info and user_info['password_hash'] and check_password_hash(user_info['password_hash'], password_attempt):
        print(f"Login OK: {username}"); return jsonify({"success": True, "role": user_info.get('role', 'vendedor')})
    else:
        print(f"Login FAIL: {username}"); return jsonify({"success": False, "message": "Credenciales incorrectas."}), 401

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    data = load_data()
    inventory_data = { "inventory": data.get('inventory', {}), "combos": data.get('combos', {}), "presasPorPollo": data.get('presasPorPollo', {}) }
    return jsonify(inventory_data)

@app.route('/api/history', methods=['GET'])
def get_history():
    data = load_data(); return jsonify({"history": data.get('history', [])})

# --- RUTAS AGREGAR ---
@app.route('/api/add/pollos', methods=['POST'])
def add_pollos():
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400
    data = load_data(); inventory = data['inventory']; presas_por_pollo = data.get('presasPorPollo', {})
    inventory['pollosEnteros'] = inventory.get('pollosEnteros', 0) + cantidad
    for p, c in presas_por_pollo.items(): inventory['presas'][p] = inventory['presas'].get(p, 0) + cantidad * c
    log_entry = add_history_log(f"ENTRADA: {cantidad} pollos enteros agregados.")
    data['history'].insert(0, log_entry) # Añadir log a los datos
    save_data(data) # Guardar todo junto
    print(f"Agregados {cantidad} pollos.")
    return jsonify({"success": True, "message": f"{cantidad} pollos agregados."})

@app.route('/api/add/presas', methods=['POST'])
def add_presas():
    req_data = request.get_json(); tipo = req_data.get('type', '').lower(); cantidad = req_data.get('quantity')
    if not tipo or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400
    data = load_data()
    if tipo not in data.get('presasPorPollo', {}): return jsonify({"success": False, "message": f"Tipo '{tipo}' inválido."}), 400
    inventory = data['inventory']; inventory['presas'][tipo] = inventory['presas'].get(tipo, 0) + cantidad
    log_entry = add_history_log(f"ENTRADA: {cantidad} {tipo}(s) individuales agregadas.")
    data['history'].insert(0, log_entry)
    save_data(data)
    print(f"Agregadas {cantidad} {tipo}(s).")
    return jsonify({"success": True, "message": f"{cantidad} {tipo}(s) agregados."})

@app.route('/api/add/producto', methods=['POST'])
def add_producto():
    req_data = request.get_json(); nombre = req_data.get('name', '').strip().capitalize(); cantidad = req_data.get('quantity')
    if not nombre or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400
    data = load_data(); inventory = data['inventory']; inventory['productos'][nombre] = inventory['productos'].get(nombre, 0) + cantidad
    stock = inventory['productos'][nombre]
    log_entry = add_history_log(f"ENTRADA PRODUCTO: {cantidad} {nombre} (Stock: {stock}).")
    data['history'].insert(0, log_entry)
    save_data(data)
    print(f"Producto: {cantidad} x {nombre}")
    return jsonify({"success": True, "message": f"{cantidad} '{nombre}' agregados."})

# --- RUTAS VENDER Y ELIMINAR (CON DEBUG) ---

@app.route('/api/sell', methods=['POST'])
def sell_cart():
    req_data = request.get_json(); cart = req_data.get('cart')
    if not isinstance(cart, list) or not cart: return jsonify({"success": False, "message": "Carrito inválido."}), 400

    data = load_data() # Cargar datos UNA VEZ
    inventory = data['inventory'] # Trabajar directamente con la referencia
    combos_def = data.get('combos', {})
    current_presas = inventory.get('presas', {})
    current_productos = inventory.get('productos', {})

    print("--- Iniciando Venta ---")
    print("Inventario ANTES:", json.dumps(inventory)) # DEBUG
    print("Carrito recibido:", json.dumps(cart)) # DEBUG

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

    print("Requerimientos calculados:", json.dumps(requerimientos)) # DEBUG

    # Comprobar stock
    for p, cR in requerimientos['presas'].items():
        if current_presas.get(p, 0) < cR: stock_suficiente = False; items_faltantes.append(f"{p}({cR}/{current_presas.get(p, 0)})")
    for p, cR in requerimientos['productos'].items():
         if current_productos.get(p, 0) < cR: stock_suficiente = False; items_faltantes.append(f"{p}({cR}/{current_productos.get(p, 0)})")

    if not stock_suficiente:
        print(f"Venta fallida stock: {items_faltantes}"); return jsonify({"success": False, "message": f"Stock insuficiente: {', '.join(items_faltantes)}"}), 400

    # Si hay stock, descontar del inventario (modificando 'data' directamente)
    print("Stock suficiente. Descontando...")
    for p, cR in requerimientos['presas'].items(): inventory['presas'][p] -= cR
    for p, cR in requerimientos['productos'].items(): inventory['productos'][p] -= cR

    print("Inventario DESPUÉS (antes de guardar):", json.dumps(inventory)) # DEBUG

    # Generar log y añadirlo a los datos
    resumen_display = ', '.join([f"{item['cantidad']}x{item.get('display', item['nombre'])}" for item in cart])
    log_entry = add_history_log(f"VENTA CARRITO ({len(cart)} items): {resumen_display}.") # Solo formatea
    data['history'].insert(0, log_entry) # Añadir al historial en 'data'

    # Guardar TODOS los cambios (inventario + historial)
    save_data(data)
    print(f"Venta procesada y datos guardados: {resumen_display}")
    return jsonify({"success": True, "message": "Venta procesada!"})


@app.route('/api/remove/pollos', methods=['POST'])
def remove_pollos():
    req_data = request.get_json(); cantidad = req_data.get('quantity')
    if not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Cantidad inválida."}), 400
    data = load_data(); inventory = data['inventory']; presas_por_pollo = data.get('presasPorPollo', {}); current_presas = inventory.get('presas', {})
    presas_necesarias = {}; stock_presas_suficiente = True
    for p, cPP in presas_por_pollo.items():
        req = cantidad * cPP
        if current_presas.get(p, 0) < req: stock_presas_suficiente = False; presas_necesarias[p] = f"Req:{req}/Disp:{current_presas.get(p, 0)}"
    if not stock_presas_suficiente: msg = f"Presas insuficientes: {presas_necesarias}"; print(msg); return jsonify({"success": False, "message": msg}), 400
    inventory['pollosEnteros'] = max(0, inventory.get('pollosEnteros', 0) - cantidad)
    for p, cPP in presas_por_pollo.items(): inventory['presas'][p] = max(0, inventory['presas'].get(p, 0) - cantidad * cPP)
    log_entry = add_history_log(f"ELIMINACIÓN: {cantidad} pollos (merma).")
    data['history'].insert(0, log_entry)
    save_data(data)
    print(f"Eliminados {cantidad} pollos (merma).")
    return jsonify({"success": True, "message": f"{cantidad} pollos eliminados." })

@app.route('/api/remove/presas', methods=['POST'])
def remove_presas():
    req_data = request.get_json(); tipo = req_data.get('type', '').lower(); cantidad = req_data.get('quantity')
    if not tipo or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400
    data = load_data(); inventory = data['inventory']
    if tipo not in inventory.get('presas', {}): return jsonify({"success": False, "message": f"Presa '{tipo}' no existe."}), 400
    if inventory['presas'][tipo] < cantidad: msg = f"Stock insuf. {tipo} (Disp:{inventory['presas'][tipo]})"; return jsonify({"success": False, "message": msg}), 400
    inventory['presas'][tipo] -= cantidad
    log_entry = add_history_log(f"ELIMINACIÓN: {cantidad} {tipo}(s) (merma).")
    data['history'].insert(0, log_entry)
    save_data(data)
    print(f"Eliminadas {cantidad} {tipo}(s) (merma).")
    return jsonify({"success": True, "message": f"{cantidad} {tipo}(s) eliminados." })

@app.route('/api/remove/producto', methods=['POST'])
def remove_producto():
    req_data = request.get_json(); nombre = req_data.get('name', '').strip().capitalize(); cantidad = req_data.get('quantity')
    if not nombre or not isinstance(cantidad, int) or cantidad <= 0: return jsonify({"success": False, "message": "Datos inválidos."}), 400
    data = load_data(); inventory = data['inventory']
    if nombre not in inventory.get('productos', {}): return jsonify({"success": False, "message": f"Producto '{nombre}' no existe."}), 400
    if inventory['productos'][nombre] < cantidad: msg = f"Stock insuf. {nombre} (Disp:{inventory['productos'][nombre]})"; return jsonify({"success": False, "message": msg}), 400
    inventory['productos'][nombre] -= cantidad
    stock = inventory['productos'][nombre]
    log_entry = add_history_log(f"ELIMINACIÓN PRODUCTO: {cantidad} {nombre} (merma). Stock: {stock}.")
    data['history'].insert(0, log_entry)
    save_data(data)
    print(f"Eliminado producto: {cantidad} x {nombre} (merma).")
    return jsonify({"success": True, "message": f"{cantidad} '{nombre}' eliminados." })


# --- Ejecutar la Aplicación ---
if __name__ == '__main__':
    print("Iniciando servidor Flask para DESARROLLO...")
    app.run(host='0.0.0.0', port=5000, debug=True)
