import os
import json
import datetime
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, session
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from io import BytesIO

app = Flask(__name__)
app.static_folder = 'static'
app.secret_key = "supersecretkey"  # Puedes cambiarla por seguridad

# Conexión a MongoDB Atlas
client = MongoClient("mongodb+srv://carol:nJAkecG8t2qRtDvM@productos.lcuehzg.mongodb.net/")
db = client.bebidas
bebidas_col = db.bebidas
users_col = db.users
ventas_col = db.ventas
devoluciones_col = db.devoluciones

# Decorador para rutas protegidas
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Por favor inicie sesión para acceder a esta página', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Constantes
CATEGORIAS = ["ALCOHOLICAS", "NO_ALCOHOLICAS", "SNACKS"]
UNIDADES = ["Botella", "Lata", "Paquete"]

# Crear admin si no existe
with app.app_context():
    if not users_col.find_one({"username": "admin"}):
        users_col.insert_one({
            "username": "admin",
            "password": generate_password_hash("admin"),
            "role": "admin"
        })

@app.route('/')
def root():
    return redirect(url_for('home'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = users_col.find_one({"username": username})

        if user and check_password_hash(user['password'], password):
            session['user'] = username
            session['role'] = user.get('role', 'user')
            flash('Inicio de sesión exitoso', 'success')
            # Redirigir al panel de administración si el usuario es admin
            if session['role'] == 'admin':
                return redirect(url_for('admin_panel'))
            else:
                return redirect(url_for('user_panel'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Las contraseñas no coinciden', 'error')
            return redirect(url_for('register'))

        if users_col.find_one({"username": username}):
            flash('El usuario ya existe', 'error')
            return redirect(url_for('register'))

        users_col.insert_one({
            "username": username,
            "password": generate_password_hash(password),
            "role": "user"
        })

        flash('Registro exitoso. Por favor inicie sesión.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Ha cerrado sesión correctamente', 'success')
    return redirect(url_for('login'))

@app.route('/Home')
@login_required
def home():
    return render_template('home.html')

@app.route('/Insertar', methods=['GET', 'POST'])
@login_required
def insertar():
    if session.get('role') != 'admin':
        flash('No tiene permisos para acceder a esta función', 'error')
        return redirect(url_for('home'))

    if request.method == 'POST':
        nombre = request.form['nombre']
        categoria = request.form['categoria']
        marca = request.form['marca']
        unidad = request.form['unidad']
        try:
            precio = float(request.form['precio'])
            stock = int(request.form['stock'])
            if precio < 0 or stock < 0:
                flash('El precio y el stock no pueden ser valores negativos', 'error')
                return render_template('insertar.html', categorias=CATEGORIAS, unidades=UNIDADES)
        except ValueError:
            flash('Por favor, ingrese valores numéricos válidos para el precio y el stock', 'error')
            return render_template('insertar.html', categorias=CATEGORIAS, unidades=UNIDADES)

        bebidas_col.update_one(
            {"nombre": nombre, "marca": marca, "unidad": unidad},
            {"$set": {
                "categoria": categoria,
                "precio": precio,
                "stock": stock
            }},
            upsert=True
        )

        flash('Bebida agregada/actualizada correctamente', 'success')
        return redirect(url_for('registros'))

    return render_template('insertar.html', categorias=CATEGORIAS, unidades=UNIDADES)

def agrupar_por_categoria(bebidas):
    bebidas_por_categoria = {}
    for bebida in bebidas:
        categoria = bebida['categoria']
        if categoria not in bebidas_por_categoria:
            bebidas_por_categoria[categoria] = []
        bebidas_por_categoria[categoria].append(bebida)
    return bebidas_por_categoria

@app.route('/Comprar', methods=['GET', 'POST'])
@login_required
def comprar():
    bebidas = list(bebidas_col.find())
    categorias = sorted(list(bebidas_col.distinct('categoria'))) # Obtener categorías únicas y ordenarlas
    bebidas_por_categoria = agrupar_por_categoria(bebidas)


    if request.method == 'POST':
        carrito_data = request.form.get('carrito_data')
        cliente = request.form.get('cliente')

        if not carrito_data or not cliente:
            flash('El carrito está vacío o falta el nombre del cliente.', 'error')
            return render_template('comprar.html', bebidas=bebidas, categorias=categorias, bebidas_por_categoria=bebidas_por_categoria)

        try:
            carrito = json.loads(carrito_data)  # Convertir la cadena JSON a una lista de diccionarios
        except json.JSONDecodeError:
            flash('Error al procesar los datos del carrito.', 'error')
            return render_template('comprar.html', bebidas=bebidas, categorias=categorias, bebidas_por_categoria=bebidas_por_categoria)

        ventas = []
        total_compra = 0

        for item in carrito:
            bebida_id = item['id']
            cantidad = item['cantidad']

            if cantidad <= 0:
                flash('La cantidad debe ser mayor que cero', 'error')
                return render_template('comprar.html', bebidas=bebidas,  categorias=categorias, bebidas_por_categoria=bebidas_por_categoria)

            bebida = bebidas_col.find_one({"_id": ObjectId(bebida_id)})

            if not bebida or bebida['stock'] < cantidad:
                flash(f'Stock insuficiente para {bebida["nombre"]}', 'error')
                return render_template('comprar.html', bebidas=bebidas, categorias=categorias, bebidas_por_categoria=bebidas_por_categoria)

            bebidas_col.update_one(
                {"_id": ObjectId(bebida_id)},
                {"$inc": {"stock": -cantidad}}
            )

            venta = {
                "bebida_id": bebida_id,
                "bebida_nombre": bebida['nombre'],
                "cantidad": cantidad,
                "cliente": cliente,
                "precio_unitario": bebida['precio'],
                "total": bebida['precio'] * cantidad,
                "fecha": datetime.datetime.now(),
                "vendedor": session['user']
            }
            ventas.append(venta)
            total_compra += venta['total']

        venta_ids = ventas_col.insert_many(ventas).inserted_ids
        session['ultima_venta_ids'] = [str(id) for id in venta_ids]
        session['total_compra'] = total_compra

        flash(f'Compra realizada con éxito. Total: ${total_compra:.2f}', 'success')
        return redirect(url_for('generar_factura'))

    return render_template('comprar.html', bebidas=bebidas, categorias=categorias, bebidas_por_categoria=bebidas_por_categoria)


@app.route('/generar_factura')
@login_required
def generar_factura():
    venta_ids_str = session.get('ultima_venta_ids')
    total_compra = session.get('total_compra')
    if not venta_ids_str:
        flash('No hay una venta reciente para generar la factura.', 'warning')
        return redirect(url_for('home'))

    ventas = []
    for venta_id_str in venta_ids_str:
        venta = ventas_col.find_one({"_id": ObjectId(venta_id_str)})
        if not venta:
            flash('No se encontró información de alguna venta.', 'error')
            return redirect(url_for('home'))
        ventas.append(venta)

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    p.setFont("Helvetica-Bold", 16)
    p.drawString(inch, 10 * inch, "Factura de Venta")
    p.setFont("Helvetica", 12)
    p.drawString(inch, 9.5 * inch, f"Fecha: {ventas[0]['fecha'].strftime('%Y-%m-%d %H:%M:%S')}")
    p.drawString(inch, 9.25 * inch, f"Vendedor: {ventas[0]['vendedor']}")
    p.drawString(inch, 9 * inch, f"Cliente: {ventas[0]['cliente']}")
    p.line(inch, 8.75 * inch, 7.5 * inch, 8.75 * inch)

    p.drawString(inch, 8.5 * inch, "Producto")
    p.drawString(4 * inch, 8.5 * inch, "Cantidad")
    p.drawString(5 * inch, 8.5 * inch, "Precio Unitario")
    p.drawString(6.5 * inch, 8.5 * inch, "Total")
    p.line(inch, 8.25 * inch, 7.5 * inch, 8.25 * inch)

    y = 8
    for venta in ventas:
        p.drawString(inch, y * inch, venta['bebida_nombre'])
        p.drawString(4 * inch, y * inch, str(venta['cantidad']))
        p.drawString(5 * inch, y * inch, f"${venta['precio_unitario']:.2f}")
        p.drawString(6.5 * inch, y * inch, f"${venta['total']:.2f}")
        y -= 0.25
        p.line(inch, (y - 0.1) * inch, 7.5 * inch, (y - 0.1) * inch)
        y -= 0.25

    p.setFont("Helvetica-Bold", 12)
    p.drawString(5.5 * inch, y * inch, "Total:")
    p.drawString(6.5 * inch, y * inch, f"${total_compra:.2f}")

    p.showPage()
    p.save()
    buffer.seek(0)

    session.pop('ultima_venta_ids', None)  # Limpiar IDs de la sesión
    session.pop('total_compra', None)

    return send_file(buffer, as_attachment=True, download_name=f"factura_compra.pdf", mimetype='application/pdf')

@app.route('/Registros')
@login_required
def registros():
    inventario = list(bebidas_col.find())
    alcoholicas = [b for b in inventario if b['categoria'] == 'ALCOHOLICAS']
    no_alcoholicas = [b for b in inventario if b['categoria'] == 'NO_ALCOHOLICAS']
    snacks = [b for b in inventario if b['categoria'] == 'SNACKS']
    return render_template(
        'registros.html',
        alcoholicas=alcoholicas,
        no_alcoholicas=no_alcoholicas,
        snacks=snacks
    )

@app.route('/Modificar/<id>', methods=['GET', 'POST'])
@login_required
def modificar(id):
    if session.get('role') != 'admin':
        flash('No tiene permisos para acceder a esta función', 'error')
        return redirect(url_for('home'))

    bebida = bebidas_col.find_one({"_id": ObjectId(id)})

    if request.method == 'POST':
        nombre = request.form['nombre']
        categoria = request.form['categoria']
        marca = request.form['marca']
        unidad = request.form['unidad']
        try:
            precio = float(request.form['precio'])
            stock = int(request.form['stock'])
            if precio < 0 or stock < 0:
                flash('El precio y el stock no pueden ser valores negativos', 'error')
                return render_template('modificar.html', bebida=bebida, categorias=CATEGORIAS, unidades=UNIDADES)
        except ValueError:
            flash('Por favor, ingrese valores numéricos válidos para el precio y el stock', 'error')
            return render_template('modificar.html', bebida=bebida, categorias=CATEGORIAS, unidades=UNIDADES)

        bebidas_col.update_one(
            {"_id": ObjectId(id)},
            {"$set": {
                "nombre": nombre,
                "categoria": categoria,
                "marca": marca,
                "unidad": unidad,
                "precio": precio,
                "stock": stock
            }}
        )

        flash('Bebida actualizada correctamente', 'success')
        return redirect(url_for('registros'))

    return render_template('modificar.html', bebida=bebida, categorias=CATEGORIAS, unidades=UNIDADES)

@app.route('/Eliminar/<id>')
@login_required
def eliminar(id):
    if session.get('role') != 'admin':
        flash('No tiene permisos para acceder a esta función', 'error')
        return redirect(url_for('home'))

    bebidas_col.delete_one({"_id": ObjectId(id)})
    flash('Bebida eliminada correctamente', 'success')
    return redirect(url_for('registros'))

@app.route('/admin_panel')
@login_required
def admin_panel():
    if session.get('role') == 'admin':
        return render_template('admin_panel.html')
    else:
        flash('No tiene permisos para acceder a esta página', 'error')
        return redirect(url_for('home'))

@app.route('/user_panel')
@login_required
def user_panel():
    return render_template('user_panel.html')
@app.route('/ventas')
@login_required
def listar_ventas():
    """Lista todas las ventas realizadas."""
    if session.get('role') != 'admin':
        flash('No tiene permisos para acceder a esta función', 'error')
        return redirect(url_for('home'))

    ventas = list(ventas_col.find())
    return render_template('ventas.html', ventas=ventas)  # Debes crear ventas.html

@app.route('/devolver/<venta_id_str>', methods=['GET', 'POST'])
@login_required
def devolver_venta(venta_id_str):
    """Permite a los administradores registrar una devolución de una venta."""

    if session.get('role') != 'admin':
        flash('No tiene permisos para acceder a esta función', 'error')
        return redirect(url_for('home'))

    venta_id = ObjectId(venta_id_str)
    venta = ventas_col.find_one({"_id": venta_id})

    if not venta:
        flash('Venta no encontrada', 'error')
        return redirect(url_for('listar_ventas'))  # Redirige a la lista de ventas, no devoluciones

    if request.method == 'POST':
        cantidad_a_devolver = int(request.form['cantidad'])
        motivo = request.form['motivo']

        if cantidad_a_devolver <= 0 or cantidad_a_devolver > venta['cantidad']:
            flash('Cantidad a devolver no válida', 'error')
            return render_template('devolver.html', venta=venta)

        # Actualizar la venta
        nueva_cantidad = venta['cantidad'] - cantidad_a_devolver
        ventas_col.update_one({"_id": venta_id}, {"$set": {"cantidad": nueva_cantidad}})

        # Crear registro de devolución
        devolucion = {
            "venta_id": venta_id,
            "bebida_nombre": venta['bebida_nombre'],
            "cantidad_devuelta": cantidad_a_devolver,
            "motivo": motivo,
            "fecha": datetime.datetime.now(),
            "vendedor": session['user']
        }
        devoluciones_col.insert_one(devolucion)

        # Actualizar el stock de la bebida
        bebidas_col.update_one(
            {"_id": ObjectId(venta['bebida_id'])},
            {"$inc": {"stock": cantidad_a_devolver}}
        )

        flash('Devolución registrada correctamente', 'success')
        return redirect(url_for('listar_ventas'))  # Redirige a la lista de ventas después de la devolución

    return render_template('devolver.html', venta=venta)

if __name__ == '__main__':
    app.run(debug=True)
