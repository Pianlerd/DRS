from flask import Flask, render_template, request, redirect, url_for, session, Response, make_response, flash, jsonify
from xhtml2pdf import pisa
import mysql.connector
import csv
import random
import string
import sys
from io import StringIO, BytesIO
from datetime import datetime
from functools import wraps

# Imports for image generation
from PIL import Image, ImageDraw, ImageFont
import requests
import os 

# --- ONE AND ONLY ONE Flask app initialization ---
app = Flask(__name__)
# Make sure to use a strong, unique secret key here.
# For demonstration, keeping the one provided in the original code.
app.secret_key = 'trash-for-coin-secret-key-2025' 

# --- Barcode Encoding/Decoding Functions ---
def encode(x: int) -> int:
    a = 982451653
    b = 1234567891234
    m = 10000000000039 # จำนวนเฉพาะที่ใกล้เคียง 10^13
    return (a * x + b) % m

def decode(y: int) -> int:
    a = 982451653
    b = 1234567891234
    m = 10000000000039 # ต้องเป็นค่าเดียวกับ m ใน encode
    a_inv = pow(a, m - 2, m) # หา inverse ของ a mod m โดยใช้ Fermat's Little Theorem
    # Ensure the result of (y - b) is positive before modulo
    return (a_inv * (y - b + m)) % m


# --- Database Connection ---
def get_db_connection():
    """
    Establishes a connection to the MySQL database.
    Returns the connection object or None if connection fails.
    """
    try:
        conn = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="project_bin"
        )
        return conn
    except mysql.connector.Error as err:
        print(f"Error connecting to database: {err}")
        return None

# --- Role-based Access Control (RBAC) Decorators ---
def role_required(allowed_roles):
    """
    Decorator to restrict access to routes based on user roles.
    If the user is not logged in, they are redirected to the login page.
    If the user's role is not in the allowed_roles list, they are redirected to the index page.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'loggedin' not in session:
                flash('โปรดเข้าสู่ระบบเพื่อเข้าถึงหน้านี้', 'danger')
                return redirect(url_for('login'))
            
            # Use .get() to safely access 'role'
            user_role = session.get('role') 
            if user_role not in allowed_roles:
                flash(f'คุณไม่มีสิทธิ์เข้าถึงหน้านี้ ยศของคุณคือ {user_role if user_role else "ไม่ได้กำหนด"}', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- Routes ---

@app.route("/")
def root_redirect():
    """Redirects the root URL to the index page."""
    return redirect(url_for("index"))

@app.route("/index", methods=["GET", "POST"])
def index():
    """
    Home page of the Trash For Coin system, displaying usage statistics.
    Statistics are only fetched and displayed if a user is logged in.
    """
    stats = {
        'total_products': 0,
        'total_orders': 0,
        'total_categories': 0,
        'total_users': 0
    }
    conn = None
    cursor = None
    try:
        if session.get('loggedin'):
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                
                # Fetch total products
                cursor.execute("SELECT COUNT(*) FROM tbl_products")
                stats['total_products'] = cursor.fetchone()[0]
                
                # Fetch total orders
                cursor.execute("SELECT COUNT(*) FROM tbl_order")
                stats['total_orders'] = cursor.fetchone()[0]
                
                # Fetch total categories
                cursor.execute("SELECT COUNT(*) FROM tbl_category")
                stats['total_categories'] = cursor.fetchone()[0]

                # แก้ไข: ดึงจำนวนผู้ใช้ตามบทบาท (Moderator ดูเฉพาะร้านตัวเอง, Administrator ถ้ามี store_id ก็ดูเฉพาะร้านตัวเอง)
                user_role = session.get('role')
                user_store_id = session.get('store_id')
                if user_role == 'root_admin':
                    cursor.execute("SELECT COUNT(*) FROM tbl_users")
                    stats['total_users'] = cursor.fetchone()[0]
                elif user_role in ['administrator', 'moderator']:
                    if user_store_id:
                        cursor.execute("SELECT COUNT(*) FROM tbl_users WHERE store_id = %s", (user_store_id,))
                        stats['total_users'] = cursor.fetchone()[0]
                    else:
                        stats['total_users'] = 0 # If admin/mod has no store_id, show 0 or handle as an error case
    except mysql.connector.Error as err:
        print(f"Error fetching stats: {err}")
        flash(f"เกิดข้อผิดพลาดในการดึงสถิติ: {err}", 'danger')
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    
    return render_template("index.html", stats=stats)

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handles user login.
    Authenticates user credentials against tbl_users table.
    Sets session variables upon successful login.
    """
    msg = ''
    conn = None
    cursor = None
    try:
        if request.method == 'POST': # Removed direct checks for 'email' and 'password' here
            email = request.form.get('email')
            password = request.form.get('password')

            if not email or not password:
                msg = 'กรุณากรอกอีเมลและรหัสผ่านให้ครบถ้วน!'
                flash(msg, 'danger')
                return render_template('login.html', msg=msg)
            
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor(dictionary=True)
                # แก้ไข: ดึง store_id มาเก็บใน session
                cursor.execute('SELECT id, email, firstname, lastname, role, store_id FROM tbl_users WHERE email = %s AND password = %s', (email, password,))
                account = cursor.fetchone()
                
                if account:
                    session['loggedin'] = True
                    session['id'] = account['id']
                    session['email'] = account['email']
                    session['firstname'] = account['firstname']
                    session['lastname'] = account['lastname']
                    session['role'] = account['role']
                    session['store_id'] = account.get('store_id') # เก็บ store_id ใน session
                    msg = 'เข้าสู่ระบบสำเร็จ!'
                    flash(msg, 'success')
                    return redirect(url_for('index'))
                else:
                    msg = 'อีเมลหรือรหัสผ่านไม่ถูกต้อง!'
                    flash(msg, 'danger')
    except mysql.connector.Error as err:
        msg = f"เกิดข้อผิดพลาดในการเข้าสู่ระบบ: {err}"
        flash(msg, 'danger')
    except Exception as e:
        msg = f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}"
        flash(msg, 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return render_template('login.html', msg=msg)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    Handles new user registration.
    Inserts new user data into tbl_users table with 'member' role by default.
    Checks for existing email addresses.
    """
    msg = ''
    conn = None
    cursor = None
    try:
        if request.method == 'POST': # Removed direct checks for form fields here
            firstname = request.form.get('firstname')
            lastname = request.form.get('lastname')
            email = request.form.get('email')
            password = request.form.get('password')
            
            if not firstname or not lastname or not email or not password:
                msg = 'กรุณากรอกข้อมูลให้ครบถ้วน!'
                flash(msg, 'danger')
                return render_template('register.html', msg=msg) # Return early if data is missing

            conn = get_db_connection()
            if conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM tbl_users WHERE email = %s', (email,))
                account = cursor.fetchone()
                
                if account:
                    msg = 'บัญชีนี้มีอยู่แล้ว!'
                    flash(msg, 'danger')
                else:
                    cursor.execute('INSERT INTO tbl_users (firstname, lastname, email, password, role) VALUES (%s, %s, %s, %s, %s)', (firstname, lastname, email, password, 'member',))
                    conn.commit()
                    msg = 'คุณสมัครสมาชิกสำเร็จแล้ว!'
                    flash(msg, 'success')
                    return redirect(url_for('login'))
        # No else for request.method == 'POST' as the check for missing fields handles it
    except mysql.connector.Error as err:
        msg = f"เกิดข้อผิดพลาดในการสมัครสมาชิก: {err}"
        flash(msg, 'danger')
    except Exception as e:
        msg = f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}"
        flash(msg, 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return render_template('register.html', msg=msg)

@app.route('/profile', methods=['GET', 'POST'])
@role_required(['root_admin', 'administrator', 'moderator', 'member', 'viewer'])
def profile():
    """
    Allows logged-in users to manage their profile information.
    Users can update their first name, last name, email, and optionally password.
    Prevents changing email to an already existing one (excluding their own).
    """
    msg = ''
    conn = None
    cursor = None
    try:
        if request.method == 'POST': # Removed direct checks for form fields here
            if 'loggedin' in session:
                new_firstname = request.form.get('firstname')
                new_lastname = request.form.get('lastname')
                new_email = request.form.get('email')
                new_password = request.form.get('password') # Use .get()

                if not new_firstname or not new_lastname or not new_email:
                    msg = 'กรุณากรอกชื่อ นามสกุล และอีเมลให้ครบถ้วน!'
                    flash(msg, 'danger')
                    return render_template('profile.html', msg=msg, session=session) # Return early if data is missing

                conn = get_db_connection()
                if conn:
                    cursor = conn.cursor()
                    
                    # Check if the new email already exists for another user
                    cursor.execute('SELECT id FROM tbl_users WHERE email = %s AND id != %s', (new_email, session['id'],))
                    existing_email = cursor.fetchone()
                    if existing_email:
                        msg = 'อีเมลนี้มีผู้ใช้งานอื่นแล้ว!'
                        flash(msg, 'danger')
                        conn.rollback()
                        return render_template('profile.html', msg=msg, session=session)

                    # Update user information
                    if new_password:
                        cursor.execute('UPDATE tbl_users SET firstname = %s, lastname = %s, email = %s, password = %s WHERE id = %s', (new_firstname, new_lastname, new_email, new_password, session['id'],))
                    else:
                        cursor.execute('UPDATE tbl_users SET firstname = %s, lastname = %s, email = %s WHERE id = %s', (new_firstname, new_lastname, new_email, session['id'],))
                    
                    conn.commit()
                    
                    # Update session variables
                    session['firstname'] = new_firstname
                    session['lastname'] = new_lastname
                    session['email'] = new_email
                    msg = 'ข้อมูลโปรไฟล์ของคุณได้รับการอัปเดตสำเร็จ!'
                    flash(msg, 'success')
                    return redirect(url_for('profile'))
            else:
                msg = 'โปรดเข้าสู่ระบบเพื่ออัปเดตโปรไฟล์ของคุณ'
                flash(msg, 'danger')
    except mysql.connector.Error as err:
        msg = f"เกิดข้อผิดพลาดในการอัปเดตโปรไฟล์: {err}"
        flash(msg, 'danger')
        if conn: conn.rollback()
    except Exception as e:
        msg = f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}"
        flash(msg, 'danger')
        if conn: conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return render_template('profile.html', msg=msg, session=session)

@app.route('/logout')
def logout():
    """Logs out the current user by clearing session variables."""
    session.pop('loggedin', None)
    session.pop('id', None)
    session.pop('email', None)
    session.pop('firstname', None)
    session.pop('lastname', None)
    session.pop('role', None)
    session.pop('store_id', None) # Clear store_id from session
    flash('คุณได้ออกจากระบบแล้ว', 'info')
    return redirect(url_for('login'))

@app.route('/about')
def about():
    """Displays the 'About Us' page."""
    return render_template('about.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    """
    Handles the 'Contact Us' form submission.
    Currently, it just prints the form data and flashes a success message.
    """
    msg = ''
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message = request.form.get('message')
        
        # Added basic validation for contact form
        if not name or not email or not subject or not message:
            msg = 'กรุณากรอกข้อมูลสำหรับติดต่อให้ครบถ้วน!'
            flash(msg, 'danger')
            return render_template('contact.html', msg=msg)

        print(f"Contact Form: Name: {name}, Email: {email}, Subject: {subject}, Message: {message}")
        msg = 'ข้อความของคุณถูกส่งสำเร็จแล้ว!'
        flash(msg, 'success')
    return render_template('contact.html', msg=msg)

# --- Category Management ---
@app.route("/tbl_category", methods=["GET", "POST"])
@role_required(['root_admin', 'administrator', 'moderator', 'member', 'viewer']) # Allow members and viewers
def tbl_category():
    """
    Manages product categories (e.g., PET, Aluminum, Glass, Burnable, Contaminated Waste).
    Supports adding, editing, deleting, and searching categories.
    Members and Viewers can only view categories.
    """
    msg = ''
    conn = None
    cursor = None
    categories = []
    search_query = request.args.get('search', '') # Get search from GET params for initial load/reset

    try:
        conn = get_db_connection()
        if not conn:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return render_template("tbl_category.html", categories=[], search=search_query, session=session)

        cursor = conn.cursor(dictionary=True)
        
        # Check if the user has permission to modify categories
        can_modify = session.get('role') in ['root_admin', 'administrator', 'moderator']

        if request.method == "POST":
            action = request.form.get('action')

            if action == 'add' and can_modify:
                category_id = request.form.get('category_id')
                category_name = request.form.get('category_name')

                if not category_id or not category_name:
                    flash('กรุณากรอกรหัสและชื่อหมวดหมู่ให้ครบถ้วน!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_category')) # Redirect to refresh page with flash message

                cursor.execute("INSERT INTO tbl_category (category_id, category_name) VALUES (%s, %s)", (category_id, category_name))
                conn.commit()
                msg = 'เพิ่มหมวดหมู่สำเร็จ!'
                flash(msg, 'success')

            elif action == 'edit' and can_modify:
                cat_id = request.form.get('cat_id')
                category_id = request.form.get('category_id')
                category_name = request.form.get('category_name')

                if not cat_id or not category_id or not category_name:
                    flash('กรุณากรอกข้อมูลหมวดหมู่เพื่อแก้ไขให้ครบถ้วน!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_category'))

                cursor.execute("UPDATE tbl_category SET category_id = %s, category_name = %s WHERE id = %s", (category_id, category_name, cat_id))
                conn.commit()
                msg = 'อัปเดตหมวดหมู่สำเร็จ!'
                flash(msg, 'success')

            elif action == 'delete' and can_modify:
                cat_id = request.form.get('cat_id')
                if not cat_id:
                    flash('ไม่พบรหัสหมวดหมู่ที่ต้องการลบ!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_category'))

                cursor.execute("DELETE FROM tbl_category WHERE id = %s", (cat_id,))
                conn.commit()
                msg = 'ลบหมวดหมู่สำเร็จ!'
                flash(msg, 'success')
            
            # For search action, update search_query from POST form if available
            if 'search' in request.form:
                search_query = request.form['search'] # Keep using [] access for search as it's always expected if present

        # Fetch categories based on current search_query
        if search_query:
            cursor.execute("SELECT * FROM tbl_category WHERE category_name LIKE %s OR category_id LIKE %s ORDER BY id DESC", ('%' + search_query + '%', '%' + search_query + '%'))
        else:
            cursor.execute("SELECT * FROM tbl_category ORDER BY id DESC")
        categories = cursor.fetchall()

    except mysql.connector.Error as err:
        msg = f"เกิดข้อผิดพลาดในฐานข้อมูล: {err}"
        flash(msg, 'danger')
        if conn: conn.rollback()
    except Exception as e:
        msg = f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}"
        flash(msg, 'danger')
        if conn: conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return render_template("tbl_category.html", categories=categories, search=search_query, msg=msg, session=session)


@app.route("/tbl_products", methods=["GET", "POST"])
@role_required(['root_admin', 'administrator', 'moderator', 'member', 'viewer']) # Allow members and viewers
def tbl_products():
    """
    Manages products.
    Supports adding, editing, deleting, and searching products.
    Members and Viewers can only view products.
    """
    msg = ''
    conn = None
    cursor = None
    products = []
    categories = []
    search_query = request.args.get('search', '') # Get search from GET params

    try:
        conn = get_db_connection()
        if not conn:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return render_template("tbl_products.html", products=[], categories=[], search=search_query, session=session)

        cursor = conn.cursor(dictionary=True)
        
        # Fetch all categories for the product dropdown
        cursor.execute("SELECT id, category_name FROM tbl_category ORDER BY category_name")
        categories = cursor.fetchall()

        can_modify = session.get('role') in ['root_admin', 'administrator', 'moderator']

        if request.method == "POST":
            action = request.form.get('action')

            if action == 'add' and can_modify:
                products_id = request.form.get('products_id')
                product_name = request.form.get('product_name')
                stock = request.form.get('stock')
                price = request.form.get('price')
                category_id = request.form.get('category_id')
                description = request.form.get('description')
                barcode_id = request.form.get('barcode_id', None)

                # Basic validation for required fields
                if not products_id or not product_name or stock is None or price is None or not category_id:
                    flash('กรุณากรอกข้อมูลสินค้า (รหัสสินค้า, ชื่อ, สต็อก, ราคา, หมวดหมู่) ให้ครบถ้วน!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_products'))

                try:
                    stock = int(stock)
                    price = float(price)
                    category_id = int(category_id)
                except ValueError:
                    flash('สต็อก, ราคา หรือหมวดหมู่ ต้องเป็นตัวเลขที่ถูกต้อง!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_products'))
                
                cursor.execute("INSERT INTO tbl_products (products_id, products_name, stock, price, category_id, description, barcode_id) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
                               (products_id, product_name, stock, price, category_id, description, barcode_id))
                conn.commit()
                msg = 'เพิ่มสินค้าสำเร็จ!'
                flash(msg, 'success')

            elif action == 'edit' and can_modify:
                product_id = request.form.get('product_id')
                products_id = request.form.get('products_id')
                product_name = request.form.get('product_name')
                stock = request.form.get('stock')
                price = request.form.get('price')
                category_id = request.form.get('category_id')
                description = request.form.get('description')
                barcode_id = request.form.get('barcode_id', None)

                if not product_id or not products_id or not product_name or stock is None or price is None or not category_id:
                    flash('กรุณากรอกข้อมูลสินค้า (รหัสสินค้า, ชื่อ, สต็อก, ราคา, หมวดหมู่) เพื่อแก้ไขให้ครบถ้วน!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_products'))
                
                try:
                    stock = int(stock)
                    price = float(price)
                    category_id = int(category_id)
                except ValueError:
                    flash('สต็อก, ราคา หรือหมวดหมู่ ต้องเป็นตัวเลขที่ถูกต้อง!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_products'))

                cursor.execute("UPDATE tbl_products SET products_id = %s, products_name = %s, stock = %s, price = %s, category_id = %s, description = %s, barcode_id = %s WHERE id = %s", 
                               (products_id, product_name, stock, price, category_id, description, barcode_id, product_id))
                conn.commit()
                msg = 'อัปเดตสินค้าสำเร็จ!'
                flash(msg, 'success')

            elif action == 'delete' and can_modify:
                product_id = request.form.get('product_id')
                if not product_id:
                    flash('ไม่พบรหัสสินค้าที่ต้องการลบ!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_products'))

                cursor.execute("DELETE FROM tbl_products WHERE id = %s", (product_id,))
                conn.commit()
                msg = 'ลบสินค้าสำเร็จ!'
                flash(msg, 'success')

            if 'search' in request.form:
                search_query = request.form['search']

        # Fetch products based on current search_query
        if search_query:
            base_query = """
                SELECT p.*, c.category_name 
                FROM tbl_products p
                LEFT JOIN tbl_category c ON p.category_id = c.id
                WHERE p.products_name LIKE %s OR p.products_id LIKE %s OR c.category_name LIKE %s OR p.barcode_id LIKE %s 
                ORDER BY p.id DESC
            """
            query_params = ('%' + search_query + '%', '%' + search_query + '%', '%' + search_query + '%', '%' + search_query + '%')
            cursor.execute(base_query, query_params)
        else:
            base_query = """
                SELECT p.*, c.category_name 
                FROM tbl_products p
                LEFT JOIN tbl_category c ON p.category_id = c.id
                ORDER BY p.id DESC
            """
            cursor.execute(base_query)
        products = cursor.fetchall()

    except mysql.connector.Error as err:
        msg = f"เกิดข้อผิดพลาดในฐานข้อมูล: {err}"
        flash(msg, 'danger')
        if conn: conn.rollback()
    except Exception as e:
        msg = f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}"
        flash(msg, 'danger')
        if conn: conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return render_template("tbl_products.html", products=products, categories=categories, search=search_query, msg=msg, session=session)
   
   
# --- Order Management ---

@app.route("/tbl_order", methods=["GET", "POST"])
@role_required(['root_admin', 'administrator', 'moderator', 'member', 'viewer'])
def tbl_order():
    """
    Manages customer orders, including quantity tracking and disposed quantity.
    Supports adding, editing, deleting, and searching orders.
    Stock is updated based on ordered quantity.
    Members and Viewers can only view orders.
    Moderators can only view orders within their store.
    """
    msg = ''
    conn = None
    cursor = None
    orders = []
    products_data = []
    users_data = []
    search_query = request.args.get('search', '')

    try:
        conn = get_db_connection()
        if not conn:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return render_template("tbl_order.html", orders=[], products=[], users=[], search=search_query, session=session)

        cursor = conn.cursor(dictionary=True)

        # Fetch all products for the product dropdowns in modals
        cursor.execute("SELECT products_id, products_name, stock, price FROM tbl_products ORDER BY products_name")
        products_data = cursor.fetchall()

        # Fetch all users for the email dropdown in modals (if admin/moderator)
        if session.get('role') in ['root_admin', 'administrator', 'moderator']:
            cursor.execute("SELECT email, CONCAT(firstname, ' ', lastname) as fullname FROM tbl_users ORDER BY firstname")
            users_data = cursor.fetchall()

        can_modify = session.get('role') in ['root_admin', 'administrator', 'moderator']

        if request.method == "POST":
            action = request.form.get('action')

            if action == 'add' and can_modify:
                order_id = request.form.get('order_id')
                products_id = request.form.get('products_id')
                quantity_str = request.form.get('quantity')
                disquantity_str = request.form.get('disquantity')
                barcode_id = request.form.get('barcode_id', None) 
                
                # Determine order email based on user role (admins/moderators can pick, others use their own)
                email = request.form.get('email') if session.get('role') in ['root_admin', 'administrator', 'moderator'] else session.get('email')

                if not order_id or not products_id or quantity_str is None or disquantity_str is None or not email:
                    flash('กรุณากรอกข้อมูลคำสั่งซื้อ (รหัสคำสั่งซื้อ, สินค้า, จำนวน, จำนวนทิ้ง, อีเมล) ให้ครบถ้วน!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_order'))

                try:
                    quantity = int(quantity_str)
                    disquantity = int(disquantity_str)
                except ValueError:
                    flash('จำนวนและจำนวนทิ้งต้องเป็นตัวเลข!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_order'))

                # Validate product existence and stock availability
                cursor.execute("SELECT products_name, stock, price FROM tbl_products WHERE products_id = %s", (products_id,))
                product_info = cursor.fetchone()

                if not product_info:
                    msg = "ไม่พบสินค้า!"
                    flash(msg, 'danger')
                elif quantity > product_info['stock']:
                    msg = f"สินค้า {product_info['products_name']} มีสต็อกไม่พอ. มีในสต็อก: {product_info['stock']}"
                    flash(msg, 'danger')
                else:
                    products_name = product_info['products_name']
                    
                    # Insert new order with user-provided disquantity and barcode_id
                    cursor.execute("""
                        INSERT INTO tbl_order (order_id, products_id, products_name, quantity, disquantity, email, barcode_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (order_id, products_id, products_name, quantity, disquantity, email, barcode_id))

                    # Update product stock (deduct ordered quantity)
                    cursor.execute("UPDATE tbl_products SET stock = stock - %s WHERE products_id = %s", (quantity, products_id))

                    conn.commit()
                    msg = 'เพิ่มคำสั่งซื้อสำเร็จและอัปเดตสต็อกสินค้าแล้ว!'
                    flash(msg, 'success')
                return redirect(url_for('tbl_order')) # Redirect after add attempt

            elif action == 'edit' and can_modify:
                ord_id = request.form.get('ord_id')
                order_id = request.form.get('order_id')
                products_id = request.form.get('products_id')
                quantity_str = request.form.get('quantity')
                disquantity_str = request.form.get('disquantity') 
                barcode_id = request.form.get('barcode_id', None) 
                email = request.form.get('email') 

                if not ord_id or not order_id or not products_id or quantity_str is None or disquantity_str is None or not email:
                    flash('กรุณากรอกข้อมูลคำสั่งซื้อเพื่อแก้ไขให้ครบถ้วน!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_order'))
                
                try:
                    quantity = int(quantity_str)
                    disquantity = int(disquantity_str)
                except ValueError:
                    flash('จำนวนและจำนวนทิ้งต้องเป็นตัวเลข!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_order'))

                # Get current order information to calculate stock change
                cursor.execute("SELECT products_id, quantity FROM tbl_order WHERE id = %s", (ord_id,))
                old_order_info = cursor.fetchone()

                if not old_order_info:
                    msg = "ไม่พบคำสั่งซื้อที่ต้องการแก้ไข!"
                    flash(msg, 'danger')
                else:
                    old_products_id = old_order_info['products_id']
                    old_quantity = old_order_info['quantity']

                    # Get new product information and its current stock
                    cursor.execute("SELECT products_name, stock FROM tbl_products WHERE products_id = %s", (products_id,))
                    new_product_info = cursor.fetchone()

                    if not new_product_info:
                        msg = "ไม่พบสินค้าใหม่ที่เลือก!"
                        flash(msg, 'danger')
                    else:
                        products_name = new_product_info['products_name']
                        current_stock_of_new_product = new_product_info['stock']

                        # --- Stock Adjustment Logic ---
                        if products_id != old_products_id:
                            # If product ID changes, restore old product's stock
                            cursor.execute("UPDATE tbl_products SET stock = stock + %s WHERE products_id = %s", (old_quantity, old_products_id))
                            
                            # Then deduct from the new product's stock
                            if quantity > current_stock_of_new_product:
                                msg = f"สินค้า {products_name} มีสต็อกไม่พอสำหรับการสั่งซื้อใหม่. มีในสต็อก: {current_stock_of_new_product}"
                                flash(msg, 'danger')
                                conn.rollback()
                                return redirect(url_for('tbl_order'))
                            cursor.execute("UPDATE tbl_products SET stock = stock - %s WHERE products_id = %s", (quantity, products_id))
                        else:
                            # If product ID is the same, adjust stock based on the difference in quantity
                            quantity_difference = quantity - old_quantity
                            if current_stock_of_new_product - quantity_difference < 0:
                                msg = f"สินค้า {products_name} มีสต็อกไม่พอสำหรับการเปลี่ยนแปลงจำนวน. มีในสต็อก: {current_stock_of_new_product}"
                                flash(msg, 'danger')
                                conn.rollback()
                                return redirect(url_for('tbl_order'))
                            cursor.execute("UPDATE tbl_products SET stock = stock - %s WHERE products_id = %s", (quantity_difference, products_id))
                        
                        # Update the order in tbl_order with new values, including disquantity and barcode_id
                        cursor.execute("""
                            UPDATE tbl_order SET order_id = %s, products_id = %s, products_name = %s, quantity = %s, disquantity = %s, email = %s, barcode_id = %s
                            WHERE id = %s
                        """, (order_id, products_id, products_name, quantity, disquantity, email, barcode_id, ord_id))

                        conn.commit()
                        msg = 'อัปเดตคำสั่งซื้อสำเร็จและอัปเดตสต็อกสินค้าแล้ว!'
                        flash(msg, 'success')
                return redirect(url_for('tbl_order')) # Redirect after edit attempt

            elif action == 'delete' and can_modify:
                ord_id = request.form.get('ord_id')
                if not ord_id:
                    flash('ไม่พบรหัสคำสั่งซื้อที่ต้องการลบ!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_order'))
                
                # Get order information before deleting to restore stock
                cursor.execute("SELECT products_id, quantity FROM tbl_order WHERE id = %s", (ord_id,))
                order_to_delete = cursor.fetchone()

                if not order_to_delete:
                    msg = "ไม่พบคำสั่งซื้อที่ต้องการลบ!"
                    flash(msg, 'danger')
                else:
                    product_id_to_restore = order_to_delete['products_id']
                    quantity_to_restore = order_to_delete['quantity']

                    # Delete the order from tbl_order
                    cursor.execute("DELETE FROM tbl_order WHERE id = %s", (ord_id,))

                    # Restore product stock in tbl_products (based on original ordered quantity)
                    cursor.execute("UPDATE tbl_products SET stock = stock + %s WHERE products_id = %s", (quantity_to_restore, product_id_to_restore))

                    conn.commit()
                    msg = 'ลบคำสั่งซื้อสำเร็จและคืนสต็อกสินค้าแล้ว!'
                    flash(msg, 'success')
                return redirect(url_for('tbl_order')) # Redirect after delete attempt

            # Handle search within POST if not handled by other actions
            if 'search' in request.form:
                search_query = request.form['search']
        
        # Build query for displaying orders (GET or after POST actions)
        base_query = """
            SELECT 
                o.id, 
                o.order_id, 
                o.products_id, 
                o.products_name, 
                o.quantity, 
                o.disquantity, 
                o.email, 
                o.order_date,
                o.barcode_id,
                p.category_id,
                p.price 
            FROM tbl_order o
            LEFT JOIN tbl_products p ON o.products_id = p.products_id
            LEFT JOIN tbl_users u ON o.email = u.email
        """
        query_params = []
        where_clauses = []

        if session.get('role') == 'member':
            where_clauses.append("o.email = %s")
            query_params.append(session['email'])
        elif session.get('role') == 'moderator': 
            user_store_id = session.get('store_id')
            if user_store_id:
                where_clauses.append("u.store_id = %s")
                query_params.append(user_store_id)
            else:
                flash("คุณไม่ได้ถูกกำหนดร้านค้า จึงไม่สามารถดูข้อมูลคำสั่งซื้อได้.", 'warning')
                orders = [] # No orders to show if moderator has no store
        
        if search_query:
            search_clause = "(o.order_id LIKE %s OR o.products_name LIKE %s OR o.email LIKE %s)"
            where_clauses.append(search_clause)
            query_params.extend(['%' + search_query + '%'] * 3)

        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)

        base_query += " ORDER BY o.id DESC"
        
        # Execute query for displaying orders
        cursor.execute(base_query, tuple(query_params))
        orders = cursor.fetchall()

    except mysql.connector.Error as err:
        msg = f"เกิดข้อผิดพลาดในฐานข้อมูล: {err}"
        flash(msg, 'danger')
        if conn: conn.rollback()
    except Exception as e:
        msg = f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}"
        flash(msg, 'danger')
        if conn: conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return render_template("tbl_order.html", orders=orders, products=products_data, users=users_data, search=search_query, msg=msg, session=session)


# --- User Management ---
@app.route("/tbl_users", methods=["GET", "POST"])
@role_required(['root_admin', 'administrator', 'moderator']) 
def tbl_users():
    """
    Manages user accounts and their roles (root_admin, administrator, moderator, member, viewer).
    Supports adding, searching, editing, and deleting users.
    Root admin cannot be deleted. Administrators cannot create/edit root_admin users.
    Moderators can only manage 'member' users within their assigned store.
    """
    msg = ''
    conn = None
    cursor = None
    users = []
    stores = []
    search_query = request.args.get('search', '')

    try:
        conn = get_db_connection()
        if not conn:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return render_template("tbl_users.html", users=[], search=search_query, stores=[], session=session)

        cursor = conn.cursor(dictionary=True)

        # Fetch all stores for dropdown
        cursor.execute("SELECT store_id, store_name FROM tbl_stores ORDER BY store_name")
        stores = cursor.fetchall()

        root_admin_id = None
        cursor.execute("SELECT id FROM tbl_users WHERE role = 'root_admin' LIMIT 1")
        result = cursor.fetchone()
        if result:
            root_admin_id = result['id']

        current_user_role = session.get('role')
        current_user_store_id = session.get('store_id')

        if request.method == "POST":
            action = request.form.get('action')

            if action == 'add':
                firstname = request.form.get('firstname')
                lastname = request.form.get('lastname')
                email = request.form.get('email')
                password = request.form.get('password')
                
                # Role and store_id for new user are determined by the current_user_role
                new_user_role = request.form.get('role') # Get from form initially
                new_user_store_id = request.form.get('store_id') # Get from form initially

                # Basic validation for required fields
                if not firstname or not lastname or not email or not password:
                    flash('กรุณากรอกข้อมูลผู้ใช้งาน (ชื่อ, นามสกุล, อีเมล, รหัสผ่าน) ให้ครบถ้วน!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))

                # --- Permission check for adding user ---
                permission_granted_for_add = False
                if current_user_role == 'root_admin':
                    permission_granted_for_add = True
                    # If root_admin, allow setting any role/store_id as submitted by form
                    if new_user_store_id:
                        try:
                            new_user_store_id = int(new_user_store_id)
                        except ValueError:
                            new_user_store_id = None
                elif current_user_role == 'administrator':
                    # Admin can't create root_admin
                    if new_user_role == 'root_admin':
                        flash("คุณไม่มีสิทธิ์เพิ่มผู้ใช้งาน Root Admin!", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    
                    # Admin can only add users to their own store if they are store-bound
                    if current_user_store_id:
                        if new_user_store_id and int(new_user_store_id) != current_user_store_id:
                            flash("Administrator สามารถเพิ่มผู้ใช้ได้เฉพาะในร้านค้าของตนเองเท่านั้น", 'danger')
                            conn.rollback()
                            return redirect(url_for('tbl_users'))
                        new_user_store_id = current_user_store_id # Force to admin's store_id
                    
                    if new_user_store_id: # Ensure it's an int if not None
                        try:
                            new_user_store_id = int(new_user_store_id)
                        except ValueError:
                            new_user_store_id = None

                    permission_granted_for_add = True

                elif current_user_role == 'moderator':
                    # Moderator can only add 'member' users
                    if new_user_role != 'member': # If they try to set another role
                        flash("Moderator สามารถเพิ่มได้เฉพาะผู้ใช้งานยศ 'member' เท่านั้น!", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    
                    # Moderator can only add users to their own store
                    if not current_user_store_id:
                        flash("Moderator ของคุณไม่ได้ถูกกำหนดร้านค้า ไม่สามารถเพิ่มผู้ใช้งานได้.", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    
                    # Force role and store_id for moderator adds
                    new_user_role = 'member'
                    new_user_store_id = current_user_store_id
                    permission_granted_for_add = True
                    
                if not permission_granted_for_add:
                    flash("คุณไม่มีสิทธิ์เพิ่มผู้ใช้งานด้วยบทบาทนี้.", 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))

                # Check for existing email
                cursor.execute('SELECT id FROM tbl_users WHERE email = %s', (email,))
                existing_email = cursor.fetchone()
                if existing_email:
                    flash('อีเมลนี้มีผู้ใช้งานอื่นแล้ว!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))

                sql_insert = 'INSERT INTO tbl_users (firstname, lastname, email, password, role, store_id) VALUES (%s, %s, %s, %s, %s, %s)'
                cursor.execute(sql_insert, (firstname, lastname, email, password, new_user_role, new_user_store_id))
                conn.commit()
                flash('เพิ่มผู้ใช้งานสำเร็จ!', 'success')

            elif action == 'edit':
                user_id = request.form.get('user_id')
                firstname = request.form.get('firstname')
                lastname = request.form.get('lastname')
                email = request.form.get('email')
                password = request.form.get('password') # Use .get()
                
                # Get submitted role and store_id (these might be ignored based on permissions)
                submitted_role = request.form.get('role')
                submitted_store_id = request.form.get('store_id')

                # Basic validation for required fields
                if not user_id or not firstname or not lastname or not email:
                    flash('กรุณากรอกข้อมูลผู้ใช้งานเพื่อแก้ไข (ชื่อ, นามสกุล, อีเมล) ให้ครบถ้วน!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))

                cursor.execute("SELECT role, store_id FROM tbl_users WHERE id = %s", (user_id,))
                target_user_data = cursor.fetchone()
                if not target_user_data:
                    flash("ไม่พบผู้ใช้งานที่ต้องการแก้ไข.", 'danger')
                    conn.rollback() 
                    return redirect(url_for('tbl_users'))
                
                target_user_role = target_user_data['role']
                target_user_store_id = target_user_data['store_id']

                # --- Determine effective role and store_id for update based on permissions ---
                effective_role = target_user_role # Default to current role
                effective_store_id = target_user_store_id # Default to current store_id

                permission_granted_for_edit = False
                if current_user_role == 'root_admin':
                    # Root admin can edit anyone, but cannot demote themselves from root_admin
                    if target_user_role == 'root_admin' and submitted_role != 'root_admin' and str(user_id) == str(session['id']):
                        flash("คุณไม่สามารถเปลี่ยนยศของ Root Admin ที่เข้าสู่ระบบอยู่ได้", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    
                    # If root_admin is editing, they can change role and store_id as submitted
                    effective_role = submitted_role
                    if submitted_store_id:
                        try:
                            effective_store_id = int(submitted_store_id)
                        except ValueError:
                            effective_store_id = None
                    else:
                        effective_store_id = None # Set to NULL if empty string submitted
                    permission_granted_for_edit = True

                elif current_user_role == 'administrator':
                    # Admin cannot edit root_admin
                    if target_user_role == 'root_admin':
                        flash("คุณไม่มีสิทธิ์แก้ไขผู้ใช้งาน Root Admin.", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    
                    # Admin cannot set role to root_admin
                    if submitted_role == 'root_admin':
                        flash("คุณไม่มีสิทธิ์กำหนดให้ผู้ใช้งานเป็น Root Admin.", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    
                    # Admin can only edit users within their own store if they are store-bound
                    if current_user_store_id:
                        if target_user_store_id != current_user_store_id:
                            flash("Administrator สามารถแก้ไขผู้ใช้ได้เฉพาะในร้านค้าของตนเองเท่านั้น", 'danger')
                            conn.rollback()
                            return redirect(url_for('tbl_users'))
                        # Admin can change role but not store_id for users in their store
                        if submitted_store_id and int(submitted_store_id) != current_user_store_id:
                            flash("Administrator ไม่สามารถเปลี่ยนร้านค้าของผู้ใช้งานที่แก้ไขได้", 'danger')
                            conn.rollback()
                            return redirect(url_for('tbl_users'))
                        effective_store_id = current_user_store_id # Force to admin's store_id

                    effective_role = submitted_role # Admin can change role
                    if submitted_store_id: # Ensure it's an int if not None
                        try:
                            effective_store_id = int(submitted_store_id)
                        except ValueError:
                            effective_store_id = None
                    else:
                        effective_store_id = None

                    permission_granted_for_edit = True

                elif current_user_role == 'moderator':
                    # Moderator can only edit 'member' users in their own store
                    if target_user_role != 'member' or target_user_store_id != current_user_store_id:
                        flash("Moderator สามารถแก้ไขได้เฉพาะผู้ใช้งานยศ 'member' ในร้านค้าของตนเองเท่านั้น.", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))

                    # Moderator cannot change role or store_id during edit
                    effective_role = target_user_role # Force to original role ('member')
                    effective_store_id = target_user_store_id # Force to original store_id
                    
                    permission_granted_for_edit = True

                if not permission_granted_for_edit:
                    flash("คุณไม่มีสิทธิ์แก้ไขผู้ใช้งานรายนี้.", 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))

                # Check for existing email (excluding current user being edited)
                cursor.execute('SELECT id FROM tbl_users WHERE email = %s AND id != %s', (email, user_id,))
                existing_email = cursor.fetchone()
                if existing_email:
                    flash('อีเมลนี้มีผู้ใช้งานอื่นแล้ว!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))

                # Perform the update with effective_role and effective_store_id
                if password:
                    sql_update = 'UPDATE tbl_users SET firstname = %s, lastname = %s, email = %s, password = %s, role = %s, store_id = %s WHERE id = %s'
                    cursor.execute(sql_update, (firstname, lastname, email, password, effective_role, effective_store_id, user_id))
                else:
                    sql_update = 'UPDATE tbl_users SET firstname = %s, lastname = %s, email = %s, role = %s, store_id = %s WHERE id = %s'
                    cursor.execute(sql_update, (firstname, lastname, email, effective_role, effective_store_id, user_id))
                
                conn.commit()
                flash('อัปเดตผู้ใช้งานสำเร็จ!', 'success')

            elif action == 'delete':
                user_id = request.form.get('user_id')
                if not user_id:
                    flash('ไม่พบรหัสผู้ใช้งานที่ต้องการลบ!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))
                
                if str(user_id) == str(session['id']):
                    flash("คุณไม่สามารถลบบัญชีผู้ใช้ของคุณเองได้!", 'danger')
                    return redirect(url_for('tbl_users'))

                cursor.execute("SELECT role, store_id FROM tbl_users WHERE id = %s", (user_id,))
                target_user_data = cursor.fetchone()
                if not target_user_data:
                    flash("ไม่พบผู้ใช้งานที่ต้องการลบ.", 'danger')
                    conn.rollback() 
                    return redirect(url_for('tbl_users'))

                target_user_role = target_user_data['role']
                target_user_store_id = target_user_data['store_id']

                permission_granted_for_delete = False
                if current_user_role == 'root_admin':
                    if target_user_role == 'root_admin':
                        cursor.execute("SELECT COUNT(*) FROM tbl_users WHERE role = 'root_admin'")
                        root_admin_count = cursor.fetchone()[0]
                        if root_admin_count <= 1: 
                            flash("ไม่สามารถลบ Root Admin คนสุดท้ายได้!", 'danger')
                            return redirect(url_for('tbl_users'))
                    permission_granted_for_delete = True
                elif current_user_role == 'administrator':
                    if target_user_role == 'root_admin': # Admin cannot delete root_admin
                        flash("คุณไม่มีสิทธิ์ลบผู้ใช้งาน Root Admin.", 'danger')
                        return redirect(url_for('tbl_users'))
                    
                    # Admin can only delete users within their own store if store-bound
                    if current_user_store_id and target_user_store_id != current_user_store_id:
                        flash("Administrator สามารถลบผู้ใช้ได้เฉพาะในร้านค้าของตนเองเท่านั้น", 'danger')
                        return redirect(url_for('tbl_users'))
                    
                    permission_granted_for_delete = True
                elif current_user_role == 'moderator':
                    if target_user_role == 'member' and target_user_store_id == current_user_store_id:
                        permission_granted_for_delete = True
                    else:
                        flash("คุณไม่มีสิทธิ์ลบผู้ใช้งานรายนี้ หรือผู้ใช้งานไม่ได้อยู่ในร้านค้าของคุณ", 'danger')
                        return redirect(url_for('tbl_users'))

                if not permission_granted_for_delete:
                    flash("คุณไม่มีสิทธิ์ลบผู้ใช้งาน.", 'danger')
                    conn.rollback() 
                    return redirect(url_for('tbl_users'))

                cursor.execute("DELETE FROM tbl_users WHERE id = %s", (user_id,))
                conn.commit()
                flash('ลบผู้ใช้งานสำเร็จ!', 'success')
            
            # Update search query if a search was performed in POST
            if 'search' in request.form:
                search_query = request.form['search']
        
        # Determine SQL query and params based on user role and search query for display
        sql_select = """
            SELECT u.id, u.firstname, u.lastname, u.email, u.role, u.store_id, s.store_name
            FROM tbl_users u
            LEFT JOIN tbl_stores s ON u.store_id = s.store_id
        """
        params = []
        where_clauses = []

        if current_user_role == 'root_admin':
            # Root admin sees all users
            if search_query:
                where_clauses.append("(u.firstname LIKE %s OR u.lastname LIKE %s OR u.email LIKE %s OR u.role LIKE %s OR s.store_name LIKE %s)")
                params.extend(['%' + search_query + '%'] * 5)
        elif current_user_role in ['administrator', 'moderator']:
            if current_user_store_id:
                where_clauses.append("u.store_id = %s")
                params.append(current_user_store_id)
                if search_query:
                    where_clauses.append("(u.firstname LIKE %s OR u.lastname LIKE %s OR u.email LIKE %s OR u.role LIKE %s OR s.store_name LIKE %s)") # Added s.store_name for completeness
                    params.extend(['%' + search_query + '%'] * 5)
            else:
                flash("คุณไม่ได้ถูกกำหนดร้านค้า จึงไม่สามารถดูข้อมูลผู้ใช้งานได้.", 'danger')
                users = [] # No users to show if admin/mod has no store

        if where_clauses:
            sql_select += " WHERE " + " AND ".join(where_clauses)
        
        sql_select += " ORDER BY u.id DESC"

        # Execute query for displaying users (only if users list is not empty due to permission)
        if current_user_role == 'root_admin' or (current_user_role in ['administrator', 'moderator'] and current_user_store_id):
            cursor.execute(sql_select, tuple(params))
            users = cursor.fetchall()
        else: # If admin/mod without store_id, users will remain empty
            users = []

    except mysql.connector.Error as err:
        msg = f"เกิดข้อผิดพลาดในฐานข้อมูล: {err}"
        flash(msg, 'danger')
        if conn: conn.rollback()
    except Exception as e:
        msg = f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}"
        flash(msg, 'danger')
        if conn: conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return render_template("tbl_users.html", users=users, search=search_query, stores=stores, session=session)

@app.route("/assign_store", methods=["POST"])
@role_required(['root_admin', 'administrator'])
def assign_store():
    """
    Allow Root Admin and Administrator to assign a store to a user.
    """
    conn = None
    cursor = None
    try:
        user_id = request.form.get('user_id')
        store_id = request.form.get('store_id')
        
        # Determine current user's role and store_id
        current_user_role = session.get('role')
        current_user_store_id = session.get('store_id')

        if store_id:
            try:
                store_id = int(store_id)
            except ValueError:
                store_id = None 
        else:
            store_id = None

        if not user_id: # Basic validation for user_id
            flash("ไม่พบรหัสผู้ใช้งานที่ต้องการกำหนดร้านค้า.", 'danger')
            return redirect(url_for('tbl_users'))

        # Get target user's current role and store_id from DB
        conn = get_db_connection()
        if conn: 
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT role, store_id FROM tbl_users WHERE id = %s", (user_id,))
            target_user_data = cursor.fetchone()

            if not target_user_data:
                flash("ไม่พบผู้ใช้งานที่ต้องการกำหนดร้านค้า.", 'danger')
                conn.rollback()
                return redirect(url_for('tbl_users'))
            
            target_user_role = target_user_data['role']
            target_user_store_id = target_user_data['store_id']

            permission_granted = False
            if current_user_role == 'root_admin':
                permission_granted = True
            elif current_user_role == 'administrator':
                # Admin can't assign store to root_admin
                if target_user_role == 'root_admin':
                    flash("คุณไม่มีสิทธิ์กำหนดร้านค้าให้ผู้ใช้งาน Root Admin.", 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))
                
                # Admin can only assign/reassign stores within their own store's scope
                # If current admin is store-bound, they can only assign to users within their store,
                # or assign NULL to users in their store if removing them from a store.
                if current_user_store_id:
                    if target_user_store_id != current_user_store_id and target_user_store_id is not None:
                        flash("Administrator สามารถกำหนดร้านค้าให้ผู้ใช้ได้เฉพาะในร้านค้าของตนเองเท่านั้น", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    if store_id is not None and store_id != current_user_store_id:
                        flash("Administrator ไม่สามารถกำหนดร้านค้าให้ผู้ใช้นอกร้านค้าของตนเองได้", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    
                    # If target user has no store and admin has a store, admin can assign to their store
                    if target_user_store_id is None and store_id is not None and store_id == current_user_store_id:
                        permission_granted = True
                    # If target user is in admin's store, admin can re-assign within their store or set to NULL
                    elif target_user_store_id == current_user_store_id:
                        permission_granted = True
                    else:
                         flash("Administrator ไม่มีสิทธิ์กำหนดร้านค้าแบบนี้.", 'danger')
                         conn.rollback()
                         return redirect(url_for('tbl_users'))
                else: # Admin is not store-bound, can assign any store (but not to root_admin)
                    permission_granted = True

            if not permission_granted:
                flash("คุณไม่มีสิทธิ์กำหนดร้านค้าสำหรับผู้ใช้งานรายนี้.", 'danger')
                conn.rollback()
                return redirect(url_for('tbl_users'))
                
            if store_id is None:
                cursor.execute("UPDATE tbl_users SET store_id = NULL WHERE id = %s", (user_id,))
            else:
                cursor.execute("UPDATE tbl_users SET store_id = %s WHERE id = %s", (store_id, user_id))
            conn.commit()
            flash(f"User ID {user_id} assigned to store ID {store_id if store_id is not None else 'NULL'} successfully.", 'success')
        else:
            flash("Database connection failed.", 'danger') 
    except mysql.connector.Error as err:
        flash(f"Error assigning store: {err}", 'danger')
        if conn: conn.rollback()
    except Exception as e:
        flash(f"An unexpected error occurred: {e}", 'danger')
        if conn: conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('tbl_users'))

# --- Barcode Scanner Route ---
@app.route("/barcode_scanner")
def barcode_scanner():
   return render_template("barcode_scanner.html")

@app.route("/generate_barcode", methods=['POST'])
def generate_barcode():
    conn = None
    cursor = None
    try:
        if not session.get('loggedin'):
            flash("กรุณาเข้าสู่ระบบ", 'danger')
            return redirect(url_for('login'))

        conn = get_db_connection()
        if not conn:
            flash("ไม่สามารถเชื่อมต่อฐานข้อมูลได้.", 'danger')
            return redirect(url_for('index')) 

        cursor = conn.cursor(dictionary=True)
        product_id = request.form.get('product_id')
        if not product_id:
            flash("รหัสสินค้าไม่ถูกต้อง.", 'danger')
            return redirect(url_for('tbl_products')) 

        encoded_id = encode(int(product_id))
        barcode_value = str(encoded_id) 

        width, height = 300, 100
        image = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(image)

        try:
            font_path = "arial.ttf" 
            font_size = 24
            font = ImageFont.truetype(font_path, font_size)
        except IOError:
            font = ImageFont.load_default()
            print("Warning: Custom font not found. Using default font.")

        for i, bit in enumerate(barcode_value):
            if bit == '1':
                draw.line([(i * 3, 0), (i * 3, height)], fill='black', width=3)
        
        text = f"ID: {product_id} | Barcode: {barcode_value}"
        text_bbox = draw.textbbox((0,0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        text_x = (width - text_width) / 2
        text_y = height - text_height - 5 

        draw.text((text_x, text_y), text, fill='black', font=font)

        img_io = BytesIO()
        image.save(img_io, 'PNG')
        img_io.seek(0)

        response = make_response(img_io.getvalue())
        response.headers['Content-Type'] = 'image/png'
        return response

    except ValueError:
        flash("รหัสสินค้าไม่ถูกต้อง (ต้องเป็นตัวเลข).", 'danger')
        return redirect(url_for('tbl_products')) 
    except mysql.connector.Error as err:
        flash(f"เกิดข้อผิดพลาดจากฐานข้อมูล: {err}", 'danger')
        return redirect(url_for('tbl_products')) 
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการสร้างบาร์โค้ด: {e}", 'danger')
        return redirect(url_for('tbl_products')) 
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# --- Report Generation ---
@app.route("/export_products_csv")
@role_required(['root_admin', 'administrator', 'moderator'])
def export_products_csv():
    """Exports product data to a CSV file."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return redirect(url_for('tbl_products'))
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT products_id, products_name, stock, price, category_id, description, barcode_id FROM tbl_products")
        products = cursor.fetchall()
        
        si = StringIO()
        cw = csv.writer(si)
        
        cw.writerow(['Product ID', 'Product Name', 'Stock', 'Price', 'Category ID', 'Description', 'Barcode ID'])
        
        for product in products:
            cw.writerow([product['products_id'], product['products_name'], product['stock'], product['price'], product['category_id'], product['description'], product['barcode_id']])
        
        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = "attachment; filename=products_report.csv"
        output.headers["Content-type"] = "text/csv"
        return output
    except mysql.connector.Error as err:
        flash(f"เกิดข้อผิดพลาดในการส่งออกข้อมูลสินค้า: {err}", 'danger')
        if conn: conn.rollback()
        return redirect(url_for('tbl_products'))
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
        if conn: conn.rollback()
        return redirect(url_for('tbl_products'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/export_orders_pdf")
@role_required(['root_admin', 'administrator', 'moderator', 'member'])
def export_orders_pdf():
    """Exports order data to a PDF file."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return redirect(url_for('tbl_order'))

        cursor = conn.cursor(dictionary=True)
        base_query = """
            SELECT 
                o.id, 
                o.order_id, 
                o.products_id, 
                o.products_name, 
                o.quantity, 
                o.disquantity, 
                o.email, 
                o.order_date,
                o.barcode_id, 
                p.category_id,
                p.price 
            FROM tbl_order o
            LEFT JOIN tbl_products p ON o.products_id = p.products_id
            LEFT JOIN tbl_users u ON o.email = u.email
        """
        query_params = []
        if session.get('role') == 'member':
            base_query += " WHERE o.email = %s"
            query_params.append(session['email'])
        elif session.get('role') == 'moderator': 
            user_store_id = session.get('store_id')
            if user_store_id:
                base_query += " WHERE u.store_id = %s"
                query_params.append(user_store_id)
            else:
                flash("คุณไม่มีสิทธิ์ส่งออกข้อมูลคำสั่งซื้อ. (ไม่ได้กำหนดร้านค้า)", 'warning')
                return redirect(url_for('tbl_order'))
        
        base_query += " ORDER BY o.order_date DESC"
        
        cursor.execute(base_query, tuple(query_params))
        orders = cursor.fetchall()

        html = render_template("pdf_template_orders.html", orders=orders)
        
        pdf_buffer = BytesIO()
        pisa_status = pisa.CreatePDF(html, dest=pdf_buffer)

        if pisa_status.err:
            flash(f"เกิดข้อผิดพลาดในการสร้าง PDF: {pisa_status.err}", 'danger')
            return redirect(url_for('tbl_order'))

        pdf_buffer.seek(0)
        
        response = make_response(pdf_buffer.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=orders_report.pdf"
        response.headers["Content-type"] = "application/pdf"
        return response
    except mysql.connector.Error as err:
        flash(f"เกิดข้อผิดพลาดในการส่งออกรายงานคำสั่งซื้อ: {err}", 'danger')
        if conn: conn.rollback()
        return redirect(url_for('tbl_order'))
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิดในการส่งออก PDF: {e}", 'danger')
        if conn: conn.rollback()
        return redirect(url_for('tbl_order'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/export_orders_csv")
@role_required(['root_admin', 'administrator', 'moderator', 'member'])
def export_orders_csv():
    """Exports order data to a CSV file."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            flash("ไม่สามารถเชื่อมต่อฐานข้อมูล.", 'danger')
            return redirect(url_for('tbl_order'))

        cursor = conn.cursor(dictionary=True)
        base_query = """
            SELECT 
                o.id, 
                o.order_id, 
                o.products_id, 
                o.products_name, 
                o.quantity, 
                o.disquantity, 
                o.email, 
                o.order_date,
                o.barcode_id, 
                p.category_id,
                p.price 
            FROM tbl_order o
            LEFT JOIN tbl_products p ON o.products_id = p.products_id
            LEFT JOIN tbl_users u ON o.email = u.email
        """
        query_params = []
        if session.get('role') == 'member':
            base_query += " WHERE o.email = %s"
            query_params.append(session['email'])
        elif session.get('role') == 'moderator': 
            user_store_id = session.get('store_id')
            if user_store_id:
                base_query += " WHERE u.store_id = %s"
                query_params.append(user_store_id)
            else:
                flash("คุณไม่มีสิทธิ์ส่งออกข้อมูลคำสั่งซื้อ. (ไม่ได้กำหนดร้านค้า)", 'warning')
                return redirect(url_for('tbl_order'))
        
        base_query += " ORDER BY o.order_date DESC"
        
        cursor.execute(base_query, tuple(query_params))
        orders = cursor.fetchall()

        si = StringIO()
        cw = csv.writer(si)

        if orders:
            header = orders[0].keys()
            cw.writerow(header)
        
        for order in orders:
            cw.writerow(order.values())
        
        output = si.getvalue()
        response = make_response(output)
        response.headers["Content-Disposition"] = "attachment; filename=orders_report.csv"
        response.headers["Content-type"] = "text/csv"
        return response

    except mysql.connector.Error as err:
        flash(f"เกิดข้อผิดพลาดในการส่งออกรายงานคำสั่งซื้อ: {err}", 'danger')
        if conn: conn.rollback()
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิดในการส่งออก CSV: {e}", 'danger')
        if conn: conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('tbl_order'))

# --- Route จัดการคำสั่งซื้อ (cart) ---
@app.route("/cart", methods=["GET", "POST"])
@role_required(['root_admin', 'administrator', 'moderator', 'member'])
def cart():
    """ 
    Handles the shopping cart functionality, including adding products,
    completing an order, and displaying the current order items.
    """
    conn = None
    cursor = None
    orders_data = []
    products_data = []
    users_data = []
    msg = ''
    pre_filled_products_id_input = ''
    current_auto_order_id = session.get('current_order_id')
    selected_product_details_display = 'จะแสดงที่นี่หลังจากระบุรหัสสินค้า'
    selected_product_barcode = session.get('current_order_barcode') or ''
    request_form_data = {}

    try:
        conn = get_db_connection()
        if not conn:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return render_template("cart.html", orders=[], products_data_string='', users=[], search='',
                                   current_auto_order_id='', selected_product_details_display='เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล',
                                   selected_product_barcode='', session=session, pre_filled_products_id_input='')

        cursor = conn.cursor(dictionary=True)

        # --- Logic for creating/managing current_order_id and barcode_id for the order ---
        if not session.get('current_order_id'):
            cursor.execute("SELECT MAX(CAST(order_id AS UNSIGNED)) AS max_order_id FROM tbl_order WHERE order_id REGEXP '^[0-9]+$'")
            result = cursor.fetchone()
            current_order_id = str(int(result['max_order_id']) + 1) if result and result['max_order_id'] is not None else '100001'
            session['current_order_id'] = current_order_id

            is_unique = False
            attempts = 0
            max_attempts = 5000
            cursor.execute("SELECT barcode_id FROM tbl_order WHERE barcode_id IS NOT NULL AND barcode_id != ''")
            existing_barcode_ids_in_db = {item['barcode_id'] for item in cursor.fetchall()}

            while not is_unique and attempts < max_attempts:
                seed = random.randint(10**11, 10**12 - 1)
                encoded_barcode_int = encode(seed)
                new_barcode = str(encoded_barcode_int).zfill(13)
                if new_barcode not in existing_barcode_ids_in_db:
                    is_unique = True
                    selected_product_barcode = new_barcode
                    session['current_order_barcode'] = selected_product_barcode
                attempts += 1

            if not is_unique:
                flash("ไม่สามารถสร้างบาร์โค้ดที่ไม่ซ้ำกันสำหรับคำสั่งซื้อใหม่ได้. โปรดลองอีกครั้ง.", 'warning')
                return redirect(url_for('cart'))

        # Fetch all product data and user data for the frontend
        cursor.execute("SELECT products_id, products_name, stock, price, barcode_id FROM tbl_products ORDER BY products_id")
        products_data = cursor.fetchall()
        products_data_parts = [f"{p['products_id']}|{str(p['products_name']).replace('|', ' ').replace('///', ' ')}|{p['stock']}|{p['price']}|{str(p['barcode_id'] or '').replace('|', ' ').replace('///', ' ')}" for p in products_data]
        products_data_string = "///".join(products_data_parts)
        
        if session.get('role') in ['root_admin', 'administrator', 'moderator']:
            cursor.execute("SELECT email, CONCAT(firstname, ' ', lastname) as fullname FROM tbl_users ORDER BY firstname")
            users_data = cursor.fetchall()

        if request.method == "POST":
            request_form_data = request.form.to_dict() # Store all POST form data
            action = request.form.get('action')

            if action == 'complete_order':
                if session.get('role') in ['root_admin', 'administrator', 'moderator', 'member']:
                    cursor.execute("""
                        SELECT o.*, p.price
                        FROM tbl_order o
                        JOIN tbl_products p ON o.products_id = p.products_id
                        WHERE o.order_id = %s
                        ORDER BY o.id
                    """, (current_order_id,))
                    orders_to_complete = cursor.fetchall()
                    
                    if not orders_to_complete:
                        flash('ไม่พบรายการสินค้าในคำสั่งซื้อนี้.', 'danger')
                        return redirect(url_for('cart'))

                    total_quantity = sum(item['quantity'] for item in orders_to_complete)
                    total_price = sum(item['quantity'] * item['price'] for item in orders_to_complete)
                    
                    session['receipt_data'] = {
                        'orders': orders_to_complete,
                        'barcode_id': selected_product_barcode,
                        'total_quantity': total_quantity,
                        'total_price': total_price,
                        'current_order_id': current_order_id
                    }
                    session.pop('current_order_id', None)
                    session.pop('current_order_barcode', None)
                    
                    flash('คำสั่งซื้อเสร็จสมบูรณ์แล้ว!', 'success')
                    return redirect(url_for('receipt_display'))
                else:
                    flash("คุณไม่มีสิทธิ์ดำเนินการคำสั่งซื้อนี้", 'danger')
                    return redirect(url_for('cart'))

            if 'products_id_input' in request.form and session.get('role') in ['root_admin', 'administrator', 'moderator', 'member']:
                products_id_input = request.form.get('products_id_input')
                pre_filled_products_id_input = products_id_input

                if not products_id_input: # Check for empty string or None
                    flash("กรุณากรอกรหัสสินค้า!", 'danger')
                    return redirect(url_for('cart'))
                if not products_id_input.isdigit() or len(products_id_input) != 13:
                    flash("รหัสสินค้าต้องเป็นตัวเลข 13 หลัก!", 'danger')
                    return redirect(url_for('cart'))

                cursor.execute("SELECT products_id, products_name, stock, price FROM tbl_products WHERE products_id = %s", (products_id_input,))
                product_info = cursor.fetchone()
                
                if not product_info:
                    flash("ไม่พบสินค้าตามบาร์โค้ดที่ระบุ!", 'danger')
                    return redirect(url_for('cart'))

                order_id_to_use = session.get('current_order_id')
                barcode_to_use_for_add = session.get('current_order_barcode')

                if not order_id_to_use or not barcode_to_use_for_add:
                    flash("ไม่สามารถดำเนินการได้: รหัสคำสั่งซื้อหรือบาร์โค้ดคำสั่งซื้อปัจจุบันไม่พร้อมใช้งาน.", 'danger')
                    return redirect(url_for('cart'))

                email = request.form.get('email')
                if session.get('role') == 'member':
                    email = session['email']
                elif not email:
                    flash("กรุณาระบุอีเมลลูกค้า.", 'danger')
                    return redirect(url_for('cart'))

                quantity = 1
                disquantity = 0

                if quantity > product_info['stock']:
                    flash(f"สินค้า {product_info['products_name']} มีสต็อกไม่พอ. มีในสต็อก: {product_info['stock']}", 'danger')
                    return redirect(url_for('cart'))
                
                products_name = product_info['products_name']
                products_id_to_use = product_info['products_id']
                
                cursor.execute("SELECT id, quantity FROM tbl_order WHERE products_id = %s AND order_id = %s AND email = %s",
                               (products_id_to_use, order_id_to_use, email))
                existing_order_item = cursor.fetchone()

                if existing_order_item:
                    new_qty = existing_order_item['quantity'] + quantity
                    if new_qty > product_info['stock']:
                        flash(f"ไม่สามารถเพิ่มได้ สินค้า {products_name} มีสต็อกไม่พอสำหรับยอดรวม. มีในสต็อก: {product_info['stock']}", 'danger')
                    else:
                        cursor.execute("UPDATE tbl_order SET quantity = %s WHERE id = %s", (new_qty, existing_order_item['id']))
                        cursor.execute("UPDATE tbl_products SET stock = stock - %s WHERE products_id = %s", (quantity, products_id_to_use))
                        conn.commit()
                        flash(f'เพิ่มจำนวนสินค้า {products_name} ในรายการสั่งซื้อ {order_id_to_use} สำเร็จ และอัปเดตสต็อกแล้ว!', 'success')
                else:
                    cursor.execute("""
                        INSERT INTO tbl_order (order_id, products_id, products_name, quantity, disquantity, email, barcode_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (order_id_to_use, products_id_to_use, products_name, quantity, disquantity, email, barcode_to_use_for_add))
                    cursor.execute("UPDATE tbl_products SET stock = stock - %s WHERE products_id = %s", (quantity, products_id_to_use))
                    conn.commit()
                    flash('เพิ่มคำสั่งซื้อสำเร็จและอัปเดตสต็อกสินค้าแล้ว!', 'success')
                return redirect(url_for('cart'))
            elif 'products_id_input' in request.form:
                flash("คุณไม่มีสิทธิ์เพิ่มคำสั่งซื้อ", 'danger')
                return redirect(url_for('cart'))
        
        # --- For GET Request and final display of current order items ---
        base_order_query = """
            SELECT o.*, p.price, p.products_name AS product_name_from_db
            FROM tbl_order o
            JOIN tbl_products p ON o.products_id = p.products_id
            LEFT JOIN tbl_users u ON o.email = u.email
            WHERE o.order_id = %s
        """
        query_params_orders = [current_auto_order_id] # Use current_auto_order_id here

        if session.get('role') == 'member':
            base_order_query += " AND o.email = %s"
            query_params_orders.append(session['email'])
        elif session.get('role') == 'moderator':
            user_store_id = session.get('store_id')
            if user_store_id:
                base_order_query += " AND u.store_id = %s"
                query_params_orders.append(user_store_id)
            else:
                flash("คุณไม่ได้ถูกกำหนดร้านค้า จึงไม่สามารถดูข้อมูลคำสั่งซื้อได้.", 'warning')
                orders_data = [] # No orders to show if moderator has no store
        
        base_order_query += " ORDER BY o.id DESC"
        cursor.execute(base_order_query, tuple(query_params_orders))
        orders_data = cursor.fetchall()
            
    except mysql.connector.Error as err:
        msg = f"เกิดข้อผิดพลาดในฐานข้อมูล: {err}"
        flash(msg, 'danger')
        if conn: conn.rollback()
    except Exception as e:
        msg = f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}"
        flash(msg, 'danger')
        if conn: conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return render_template("cart.html",
                           orders=orders_data,
                           products_data_string=products_data_string,
                           users=users_data,
                           search='',
                           msg=msg,
                           current_auto_order_id=current_auto_order_id,
                           request_form_data=request_form_data,
                           selected_product_details_display=selected_product_details_display,
                           selected_product_barcode=selected_product_barcode,
                           pre_filled_products_id_input=pre_filled_products_id_input,
                           session=session)

# --- New route to display the PNG receipt ---
@app.route("/receipt_display")
@role_required(['root_admin', 'administrator', 'moderator', 'member', 'viewer'])
def receipt_display():
    """
    Displays the receipt data from the session and then clears it.
    """
    receipt_data = session.pop('receipt_data', None)

    if not receipt_data:
        flash("ไม่พบข้อมูลใบเสร็จ. โปรดดำเนินการคำสั่งซื้อใหม่.", 'danger')
        return redirect(url_for('cart'))

    return render_template("receipt_png_template.html",
                           orders=receipt_data['orders'],
                           barcode_id=receipt_data['barcode_id'],
                           total_quantity=receipt_data['total_quantity'],
                           total_price=receipt_data['total_price'],
                           current_order_id=receipt_data['current_order_id'],
                           session=session)

# --- Routes สำหรับแก้ไขและลบรายการในตะกร้า (ย้ายมาอยู่นอกฟังก์ชัน cart()) ---
# แก้ไขรายการในตะกร้า
@app.route("/cart/edit/<int:item_id>", methods=["POST"])
@role_required(['root_admin', 'administrator', 'moderator', 'member'])
def edit_cart_item(item_id):
    conn_edit = None
    cursor_edit = None
    try:
        conn_edit = get_db_connection()
        if not conn_edit:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return redirect(url_for('cart'))

        cursor_edit = conn_edit.cursor(dictionary=True)
        new_quantity_str = request.form.get('quantity')
        new_disquantity_str = request.form.get('disquantity')
        products_id_from_form = request.form.get('products_id') 
        order_id_from_form = request.form.get('order_id') 
        
        if new_quantity_str is None or new_disquantity_str is None or not products_id_from_form or not order_id_from_form:
            flash('กรุณากรอกข้อมูลเพื่อแก้ไขรายการในตะกร้าให้ครบถ้วน!', 'danger')
            conn_edit.rollback()
            return redirect(url_for('cart'))

        try:
            new_quantity = int(new_quantity_str)
            new_disquantity = int(new_disquantity_str)
        except ValueError:
            flash('จำนวนและจำนวนทิ้งต้องเป็นตัวเลขที่ถูกต้อง.', 'danger')
            conn_edit.rollback()
            return redirect(url_for('cart'))

        cursor_edit.execute("SELECT stock, products_name FROM tbl_products WHERE products_id = %s", (products_id_from_form,))
        product_info = cursor_edit.fetchone()

        if not product_info:
            flash(f"ไม่พบสินค้า ID {products_id_from_form} สำหรับแก้ไข.", 'danger')
            return redirect(url_for('cart'))

        current_stock_in_db = product_info['stock']

        cursor_edit.execute("SELECT quantity, email FROM tbl_order WHERE id = %s AND order_id = %s", (item_id, order_id_from_form))
        current_order_item_info = cursor_edit.fetchone()
        
        if not current_order_item_info:
            flash("ไม่พบรายการคำสั่งซื้อที่ต้องการแก้ไข.", 'danger')
            return redirect(url_for('cart'))

        current_order_qty = current_order_item_info['quantity']
        item_owner_email = current_order_item_info['email']

        if session.get('role') == 'member' and session.get('email') != item_owner_email:
            flash("คุณไม่มีสิทธิ์แก้ไขรายการคำสั่งซื้อของผู้อื่น.", 'danger')
            return redirect(url_for('cart'))

        if new_quantity <= 0:
            flash("จำนวนสินค้าต้องมากกว่า 0 หากต้องการลบ กรุณากดปุ่มลบ.", 'warning')
            return redirect(url_for('cart'))
        
        if new_disquantity < 0:
            flash("จำนวนทิ้งต้องไม่น้อยกว่า 0.", 'warning')
            return redirect(url_for('cart'))

        if new_disquantity > new_quantity:
            flash("จำนวนทิ้งไม่สามารถมากกว่าจำนวนสินค้าทั้งหมดได้.", 'danger')
            return redirect(url_for('cart'))

        stock_to_restore = current_order_qty - new_quantity
        
        if current_stock_in_db + stock_to_restore < 0:
            flash(f"ไม่สามารถแก้ไขได้: สินค้า {product_info['products_name']} มีสต็อกไม่พอ. สต็อกปัจจุบัน: {current_stock_in_db}, ต้องการปรับ: {stock_to_restore}.", 'danger')
            return redirect(url_for('cart'))

        cursor_edit.execute("""
            UPDATE tbl_order
            SET quantity = %s, disquantity = %s
            WHERE id = %s AND order_id = %s
        """, (new_quantity, new_disquantity, item_id, order_id_from_form)) 

        cursor_edit.execute("UPDATE tbl_products SET stock = stock + %s WHERE products_id = %s", (stock_to_restore, products_id_from_form))

        conn_edit.commit()
        flash(f'แก้ไขรายการ ID {item_id} ในคำสั่งซื้อ {order_id_from_form} สำเร็จแล้ว!', 'success')

    except ValueError:
        flash("จำนวนและทิ้งต้องเป็นตัวเลขที่ถูกต้อง.", 'danger')
    except mysql.connector.Error as err:
        flash(f"เกิดข้อผิดพลาดในการแก้ไขรายการ: {err}", 'danger')
        if conn_edit: conn_edit.rollback()
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
        if conn_edit: conn_edit.rollback()
    finally:
        if cursor_edit:
            cursor_edit.close()
        if conn_edit:
            conn_edit.close()
    return redirect(url_for('cart'))

# ลบรายการในตะกร้า
@app.route("/cart/delete/<int:item_id>", methods=["POST"])
@role_required(['root_admin', 'administrator', 'moderator', 'member'])
def delete_cart_item(item_id):
    conn_del = None
    cursor_del = None
    try:
        conn_del = get_db_connection()
        if not conn_del:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return redirect(url_for('cart'))

        cursor_del = conn_del.cursor(dictionary=True)
        cursor_del.execute("SELECT products_id, quantity, order_id, email FROM tbl_order WHERE id = %s", (item_id,))
        item_to_delete = cursor_del.fetchone()

        if not item_to_delete:
            flash("ไม่พบรายการที่จะลบ.", 'danger')
            return redirect(url_for('cart'))

        item_owner_email = item_to_delete['email']
        if session.get('role') == 'member' and session.get('email') != item_owner_email:
            flash("คุณไม่มีสิทธิ์ลบรายการคำสั่งซื้อของผู้อื่น.", 'danger')
            return redirect(url_for('cart'))

        cursor_del.execute("UPDATE tbl_products SET stock = stock + %s WHERE products_id = %s",
                           (item_to_delete['quantity'], item_to_delete['products_id']))

        cursor_del.execute("DELETE FROM tbl_order WHERE id = %s", (item_id,))
        
        conn_del.commit()
        flash(f'ลบรายการ ID {item_id} ออกจากคำสั่งซื้อ {item_to_delete["order_id"]} สำเร็จแล้ว! สต็อกสินค้าได้รับการคืนแล้ว.', 'success')

    except mysql.connector.Error as err:
        flash(f"เกิดข้อผิดพลาดในการลบรายการ: {err}", 'danger')
        if conn_del: conn_del.rollback()
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
        if conn_del: conn_del.rollback()
    finally:
        if cursor_del:
            cursor_del.close()
        if conn_del:
            conn_del.close()
    return redirect(url_for('cart'))


# --- Route to manage package returns (bin) ---
@app.route("/bin", methods=["GET", "POST"])
@role_required(['root_admin', 'administrator', 'moderator', 'member', 'viewer'])
def bin():
    conn = None
    cursor = None
    orders_data = []
    barcode_id_filter = request.args.get('barcode_id_filter', '')
    request_form_data = {}

    try:
        conn = get_db_connection()
        if not conn:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return render_template("bin.html", orders=[], barcode_id_filter='', request_form_data={}, session=session)

        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            request_form_data = request.form.to_dict()
            if request.form.get('action') == 'add_disquantity':
                barcode_id_filter = request.form.get('barcode_id_for_disquantity', barcode_id_filter)
            elif request.form.get('action') == 'search':
                barcode_id_filter = request.form.get('barcode_id_filter_input', barcode_id_filter)

        if request.method == "POST" and request.form.get('action') == 'add_disquantity':
            barcode_id_to_search = request.form.get('barcode_id_for_disquantity')
            products_id_to_disquantity = request.form.get('products_id_to_disquantity')

            if not barcode_id_to_search or not products_id_to_disquantity:
                flash("กรุณาระบุรหัสบาร์โค้ดและรหัสสินค้าที่ต้องการเพิ่มจำนวนทิ้ง.", 'danger')
                return redirect(url_for('bin', barcode_id_filter=barcode_id_filter))

            base_query_item = """
                SELECT o.id, o.quantity, o.disquantity, o.products_name, o.products_id, p.stock, p.category_id, o.email, u.store_id AS user_store_id
                FROM tbl_order o
                JOIN tbl_products p ON o.products_id = p.products_id
                LEFT JOIN tbl_users u ON o.email = u.email
                WHERE o.barcode_id = %s AND o.products_id = %s
            """
            query_params_item = [barcode_id_to_search, products_id_to_disquantity]

            if session.get('role') == 'member':
                base_query_item += " AND o.email = %s"
                query_params_item.append(session['email'])
            elif session.get('role') == 'moderator':
                user_store_id = session.get('store_id')
                if user_store_id:
                    base_query_item += " AND u.store_id = %s"
                    query_params_item.append(user_store_id)
                else:
                    flash("คุณไม่ได้ถูกกำหนดร้านค้า จึงไม่มีสิทธิ์ดำเนินการนี้.", 'warning')
                    return redirect(url_for('bin', barcode_id_filter=barcode_id_filter))

            cursor.execute(base_query_item, tuple(query_params_item))
            order_item_to_update = cursor.fetchone()

            if order_item_to_update:
                current_quantity = order_item_to_update['quantity']
                current_disquantity = order_item_to_update['disquantity']
                category_id_for_bin = order_item_to_update.get('category_id')

                if category_id_for_bin is None:
                    flash(f"ไม่พบ category_id สำหรับสินค้า '{order_item_to_update['products_name']}'. ไม่สามารถอัปเดต bin ได้.", 'danger')
                    return redirect(url_for('bin', barcode_id_filter=barcode_id_filter))

                proposed_disquantity = current_disquantity + 1

                if proposed_disquantity <= current_quantity:
                    cursor.execute("UPDATE tbl_order SET disquantity = %s WHERE id = %s",
                                   (proposed_disquantity, order_item_to_update['id']))

                    cursor.execute("UPDATE tbl_bin SET value = 1 WHERE category_id = %s", (category_id_for_bin,))

                    conn.commit()
                    flash(f"เพิ่มจำนวนทิ้งสินค้า '{order_item_to_update['products_name']}' (รหัสสินค้า: {products_id_to_disquantity}) สำเร็จ. สถานะ bin (category_id: {category_id_for_bin}) ได้รับการอัปเดตแล้ว.", 'success')
                else:
                    flash(f"ไม่สามารถเพิ่มจำนวนทิ้งได้เกินจำนวนสินค้าที่สั่งซื้อ ({current_quantity} ชิ้น) สำหรับสินค้า '{order_item_to_update['products_name']}'", 'danger')
            else:
                flash("ไม่พบรายการสินค้าที่ตรงกันสำหรับรหัสบาร์โค้ดและรหัสสินค้าที่ระบุ.", 'danger')
            return redirect(url_for('bin', barcode_id_filter=barcode_id_filter))

        # Main logic for displaying order items (GET or after other POST actions)
        if barcode_id_filter:
            base_query = """
                SELECT o.*, p.price, p.products_name, p.category_id, u.email AS user_email_from_db, u.store_id AS user_store_id
                FROM tbl_order o
                JOIN tbl_products p ON o.products_id = p.products_id
                LEFT JOIN tbl_users u ON o.email = u.email
                WHERE o.barcode_id = %s
            """
            query_params = [barcode_id_filter]

            if session.get('role') == 'member':
                base_query += " AND o.email = %s"
                query_params.append(session['email'])
            elif session.get('role') == 'moderator':
                user_store_id = session.get('store_id')
                if user_store_id:
                    base_query += " AND u.store_id = %s"
                    query_params.append(user_store_id)
                else:
                    flash("คุณไม่ได้ถูกกำหนดร้านค้า จึงไม่สามารถดูข้อมูลใน Bin ได้.", 'warning')
                    orders_data = []
            
            base_query += " ORDER BY o.id DESC"
            cursor.execute(base_query, tuple(query_params))
            orders_data = cursor.fetchall()
        else:
            orders_data = []

    except mysql.connector.Error as err:
        flash(f"เกิดข้อผิดพลาดในการดึงข้อมูลคำสั่งซื้อ: {err}", 'danger')
        if conn: conn.rollback()
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
        if conn: conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return render_template("bin.html",
                           orders=orders_data,
                           barcode_id_filter=barcode_id_filter,
                           request_form_data=request_form_data,
                           session=session
                           )

# --- Routes สำหรับแก้ไขและลบรายการในระบบคืนบรรจุภัณฑ์ ---

@app.route("/bin/edit/<int:item_id>", methods=["POST"])
@role_required(['root_admin', 'administrator', 'moderator', 'member'])
def edit_bin_item(item_id):
    conn_edit = None
    cursor_edit = None
    barcode_id_for_redirect = request.form.get('barcode_id_for_redirect', '')
    try:
        conn_edit = get_db_connection()
        if not conn_edit:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))

        cursor_edit = conn_edit.cursor(dictionary=True)
        new_quantity_str = request.form.get('quantity')
        new_disquantity_str = request.form.get('disquantity')
        products_id_from_form = request.form.get('products_id')
        order_id_from_form = request.form.get('order_id')
        
        if new_quantity_str is None or new_disquantity_str is None or not products_id_from_form or not order_id_from_form:
            flash('กรุณากรอกข้อมูลเพื่อแก้ไขรายการในระบบคืนบรรจุภัณฑ์ให้ครบถ้วน!', 'danger')
            conn_edit.rollback()
            return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))

        try:
            new_quantity = int(new_quantity_str)
            new_disquantity = int(new_disquantity_str)
        except ValueError:
            flash('จำนวนและจำนวนทิ้งต้องเป็นตัวเลขที่ถูกต้อง.', 'danger')
            conn_edit.rollback()
            return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))

        cursor_edit.execute("SELECT quantity, disquantity, email FROM tbl_order WHERE id = %s AND order_id = %s", (item_id, order_id_from_form))
        old_order_item = cursor_edit.fetchone()

        if not old_order_item:
            flash(f"ไม่พบรายการ ID {item_id} สำหรับแก้ไข.", 'danger')
            return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))

        old_quantity = old_order_item['quantity']
        old_disquantity = old_order_item['disquantity']
        item_owner_email = old_order_item['email']

        if session.get('role') == 'member' and session.get('email') != item_owner_email:
            flash("คุณไม่มีสิทธิ์แก้ไขรายการ Bin ของผู้อื่น.", 'danger')
            return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))

        cursor_edit.execute("SELECT stock, products_name, category_id FROM tbl_products WHERE products_id = %s", (products_id_from_form,))
        product_info = cursor_edit.fetchone()
        if not product_info:
            flash(f"ไม่พบข้อมูลสินค้า ID {products_id_from_form}.", 'danger')
            return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))

        current_stock = product_info['stock']
        category_id_for_bin_update = product_info['category_id']

        if new_quantity <= 0:
            flash("จำนวนสินค้าต้องมากกว่า 0 หากต้องการลบ กรุณากดปุ่มลบรายการ.", 'warning')
            return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))
        
        if new_disquantity < 0:
            flash("จำนวนทิ้งต้องไม่น้อยกว่า 0.", 'warning')
            return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))

        if new_disquantity > new_quantity:
            flash("จำนวนทิ้งไม่สามารถมากกว่าจำนวนสินค้าทั้งหมดได้.", 'danger')
            return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))

        stock_change_from_quantity = old_quantity - new_quantity
        
        if current_stock + stock_change_from_quantity < 0:
            flash(f"ไม่สามารถแก้ไขได้: สินค้า '{product_info['products_name']}' มีสต็อกไม่พอสำหรับการเปลี่ยนแปลงนี้ (สต็อกปัจจุบัน: {current_stock}, ต้องการปรับ: {stock_change_from_quantity}).", 'danger')
            return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))

        cursor_edit.execute("""
            UPDATE tbl_order
            SET quantity = %s, disquantity = %s
            WHERE id = %s AND order_id = %s
        """, (new_quantity, new_disquantity, item_id, order_id_from_form))

        cursor_edit.execute("UPDATE tbl_products SET stock = stock + %s WHERE products_id = %s",
                            (stock_change_from_quantity, products_id_from_form))

        if new_disquantity > 0:
            cursor_edit.execute("UPDATE tbl_bin SET value = 1 WHERE category_id = %s", (category_id_for_bin_update,))
        else:
            pass

        conn_edit.commit()
        flash(f'แก้ไขรายการ ID {item_id} (สินค้า: {product_info["products_name"]}) ในคำสั่งซื้อ {order_id_from_form} สำเร็จแล้ว!', 'success')

    except ValueError:
        flash("จำนวนและทิ้งต้องเป็นตัวเลขที่ถูกต้อง.", 'danger')
    except mysql.connector.Error as err:
        flash(f"เกิดข้อผิดพลาดในการแก้ไขรายการ: {err}", 'danger')
        if conn_edit: conn_edit.rollback()
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
        if conn_edit: conn_edit.rollback()
    finally:
        if cursor_edit:
            cursor_edit.close()
        if conn_edit:
            conn_edit.close()
    return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))

@app.route("/bin/delete/<int:item_id>", methods=["POST"])
@role_required(['root_admin', 'administrator', 'moderator', 'member'])
def delete_bin_item(item_id):
    conn_del = None
    cursor_del = None
    item_barcode_id = ""
    try:
        conn_del = get_db_connection()
        if not conn_del:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return redirect(url_for('bin'))

        cursor_del = conn_del.cursor(dictionary=True)
        cursor_del.execute("SELECT products_id, quantity, order_id, barcode_id, email FROM tbl_order WHERE id = %s", (item_id,))
        item_to_delete = cursor_del.fetchone()

        if not item_to_delete:
            flash("ไม่พบรายการที่จะลบ.", 'danger')
            return redirect(url_for('bin'))

        item_owner_email = item_to_delete['email']
        if session.get('role') == 'member' and session.get('email') != item_owner_email:
            flash("คุณไม่มีสิทธิ์ลบรายการ Bin ของผู้อื่น.", 'danger')
            return redirect(url_for('bin'))

        item_barcode_id = item_to_delete['barcode_id']

        cursor_del.execute("UPDATE tbl_products SET stock = stock + %s WHERE products_id = %s",
                            (item_to_delete['quantity'], item_to_delete['products_id']))

        cursor_del.execute("DELETE FROM tbl_order WHERE id = %s", (item_id,))
        
        conn_del.commit()
        flash(f'ลบรายการ ID {item_id} ออกจากคำสั่งซื้อ {item_to_delete["order_id"]} สำเร็จแล้ว! สต็อกสินค้าได้รับการคืนแล้ว.', 'success')

    except mysql.connector.Error as err:
        flash(f"เกิดข้อผิดพลาดในการลบรายการ: {err}", 'danger')
        if conn_del: conn_del.rollback()
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
        if conn_del: conn_del.rollback()
    finally:
        if cursor_del:
            cursor_del.close()
        if conn_del:
            conn_del.close()
    return redirect(url_for('bin', barcode_id_filter=item_barcode_id))


if __name__ == "__main__":
    app.run(debug=True)
