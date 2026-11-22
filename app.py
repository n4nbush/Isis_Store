import os
import sqlite3
from datetime import datetime
from functools import wraps
from secrets import token_hex

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.environ.get("ISIS_STORE_DB", os.path.join(BASE_DIR, "store.db"))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "change-this-secret-key"),
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            photo TEXT,
            stock INTEGER NOT NULL CHECK (stock >= 0),
            supplier_price REAL NOT NULL CHECK (supplier_price >= 0),
            sale_price REAL NOT NULL CHECK (sale_price >= 0),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            unit_supplier_price REAL NOT NULL,
            unit_sale_price REAL NOT NULL,
            sale_date TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        """
    )
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ("admin", generate_password_hash("admin"), "admin"),
        )
    db.commit()


@app.before_request
def setup():
    init_db()
    if "csrf_token" not in session:
        session["csrf_token"] = token_hex(32)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Esta acción requiere permisos de administrador.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_context():
    return {"csrf_token": session.get("csrf_token", "")}


@app.before_request
def validate_csrf():
    if request.method == "POST":
        if request.form.get("csrf_token") != session.get("csrf_token"):
            flash("La sesión expiró. Intentá nuevamente.", "error")
            return redirect(request.referrer or url_for("login"))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("home"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["csrf_token"] = token_hex(32)
            return redirect(url_for("home"))
        flash("Usuario o contraseña incorrectos.", "error")
    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    db = get_db()
    product_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    stock_count = db.execute("SELECT COALESCE(SUM(stock), 0) FROM products").fetchone()[0]
    today = datetime.now().strftime("%Y-%m-%d")
    today_sales = db.execute(
        "SELECT COALESCE(SUM(quantity * unit_sale_price), 0) FROM sales "
        "WHERE sale_date LIKE ?",
        (today + "%",),
    ).fetchone()[0]
    return render_template(
        "home.html",
        product_count=product_count,
        stock_count=stock_count,
        today_sales=today_sales,
    )


@app.route("/products")
@login_required
def products():
    db = get_db()
    items = db.execute("SELECT * FROM products ORDER BY name").fetchall()
    return render_template("products.html", products=items)


@app.route("/products/new", methods=["GET", "POST"])
@admin_required
def new_product():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        stock = request.form.get("stock", "")
        supplier_price = request.form.get("supplier_price", "")
        sale_price = request.form.get("sale_price", "")
        try:
            stock_value = int(stock)
            supplier_value = float(supplier_price)
            sale_value = float(sale_price)
            if not name or stock_value < 0 or supplier_value < 0 or sale_value < 0:
                raise ValueError
        except (ValueError, TypeError):
            flash("Completá todos los datos con valores válidos.", "error")
            return redirect(url_for("new_product"))

        photo_name = None
        photo = request.files.get("photo")
        if photo and photo.filename:
            extension = photo.filename.rsplit(".", 1)[-1].lower()
            if extension not in ALLOWED_IMAGE_EXTENSIONS:
                flash("Formato de imagen no permitido.", "error")
                return redirect(url_for("new_product"))
            photo_name = f"{token_hex(12)}.{extension}"
            photo.save(os.path.join(app.config["UPLOAD_FOLDER"], secure_filename(photo_name)))

        db = get_db()
        db.execute(
            "INSERT INTO products (name, photo, stock, supplier_price, sale_price, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, photo_name, stock_value, supplier_value, sale_value, datetime.now().isoformat()),
        )
        db.commit()
        flash("Producto cargado correctamente.", "success")
        return redirect(url_for("products"))
    return render_template("product_form.html")


@app.post("/products/<int:product_id>/delete")
@admin_required
def delete_product(product_id):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        flash("El producto no existe.", "error")
        return redirect(url_for("products"))
    if product["photo"]:
        photo_path = os.path.join(app.config["UPLOAD_FOLDER"], product["photo"])
        if os.path.isfile(photo_path):
            os.remove(photo_path)
    db.execute("DELETE FROM sales WHERE product_id = ?", (product_id,))
    db.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.commit()
    flash("Producto eliminado.", "success")
    return redirect(url_for("products"))


@app.route("/sales/new", methods=["GET", "POST"])
@login_required
def new_sale():
    db = get_db()
    products = db.execute(
        "SELECT * FROM products WHERE stock > 0 ORDER BY name"
    ).fetchall()
    if request.method == "POST":
        try:
            product_id = int(request.form.get("product_id", ""))
            quantity = int(request.form.get("quantity", ""))
            if quantity <= 0:
                raise ValueError
        except (ValueError, TypeError):
            flash("Seleccioná un producto y una cantidad válida.", "error")
            return redirect(url_for("new_sale"))

        product = db.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if product is None:
            flash("El producto no existe.", "error")
        elif quantity > product["stock"]:
            flash("No hay stock suficiente.", "error")
        else:
            db.execute(
                "INSERT INTO sales "
                "(product_id, quantity, unit_supplier_price, unit_sale_price, sale_date) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    product_id,
                    quantity,
                    product["supplier_price"],
                    product["sale_price"],
                    datetime.now().isoformat(),
                ),
            )
            db.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ?",
                (quantity, product_id),
            )
            db.commit()
            flash("Venta registrada.", "success")
            return redirect(url_for("home"))
    return render_template("sale_form.html", products=products)


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    totals = db.execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS units,
               COALESCE(SUM(quantity * unit_sale_price), 0) AS revenue,
               COALESCE(SUM(quantity * (unit_sale_price - unit_supplier_price)), 0) AS profit
        FROM sales
        """
    ).fetchone()
    top_products = db.execute(
        """
        SELECT p.name,
               SUM(s.quantity) AS units_sold,
               SUM(s.quantity * (s.unit_sale_price - s.unit_supplier_price)) AS profit
        FROM sales s
        JOIN products p ON p.id = s.product_id
        GROUP BY p.id, p.name
        ORDER BY units_sold DESC, p.name ASC
        LIMIT 5
        """
    ).fetchall()
    recent_sales = db.execute(
        """
        SELECT s.*, p.name AS product_name
        FROM sales s
        JOIN products p ON p.id = s.product_id
        ORDER BY s.sale_date DESC
        LIMIT 10
        """
    ).fetchall()
    return render_template(
        "dashboard.html",
        totals=totals,
        top_products=top_products,
        recent_sales=recent_sales,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
