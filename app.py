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
import base64 # Import base64 for image encoding
import re # Import re for regex matching

app = Flask(__name__)
# โปรดเปลี่ยนเป็นคีย์ลับที่ปลอดภัยและไม่ซ้ำกันสำหรับแอปพลิเคชันของคุณ
app.secret_key = 'your_strong_and_secret_key_here' 

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
    # ตรวจสอบให้แน่ใจว่าผลลัพธ์ของ (y - b) เป็นบวกก่อนการ modulo
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
            database="project2"
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
            
            # ใช้ .get() เพื่อเข้าถึง 'role' อย่างปลอดภัย
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
                
                user_role = session.get('role')
                user_store_id = session.get('store_id')

                # Fetch total products (Moderator and Member see only their store's products)
                if user_role in ['moderator', 'member', 'viewer'] and user_store_id:
                    cursor.execute("SELECT COUNT(*) FROM tbl_products WHERE store_id = %s", (user_store_id,))
                else: # root_admin, administrator, or roles without store_id see all
                    cursor.execute("SELECT COUNT(*) FROM tbl_products")
                stats['total_products'] = cursor.fetchone()[0]
                
                # Fetch total orders (Moderator and Member see only their store's orders)
                if user_role in ['moderator', 'member', 'viewer'] and user_store_id:
                    cursor.execute("""
                        SELECT COUNT(id) FROM tbl_order
                        WHERE store_id = %s
                    """, (user_store_id,))
                else: # root_admin, administrator, or roles without store_id see all
                    cursor.execute("SELECT COUNT(*) FROM tbl_order")
                stats['total_orders'] = cursor.fetchone()[0]
                
                # Fetch total categories (Moderator and Member see only their store's categories)
                if user_role in ['moderator', 'member', 'viewer'] and user_store_id:
                     cursor.execute("SELECT COUNT(*) FROM tbl_category WHERE store_id = %s", (user_store_id,))
                else: # root_admin, administrator, or roles without store_id see all
                    cursor.execute("SELECT COUNT(*) FROM tbl_category")
                stats['total_categories'] = cursor.fetchone()[0]

                # Fetch total users (Moderator and Admin see users from their store; root_admin sees all)
                # Members and Viewers typically don't manage other users, so their stats here might be 0 or just themselves
                if user_role == 'root_admin':
                    cursor.execute("SELECT COUNT(*) FROM tbl_users")
                    stats['total_users'] = cursor.fetchone()[0]
                elif user_role in ['administrator', 'moderator']:
                    if user_store_id:
                        cursor.execute("SELECT COUNT(*) FROM tbl_users WHERE store_id = %s", (user_store_id,))
                        stats['total_users'] = cursor.fetchone()[0]
                    else: # Admin/Mod with no store_id might imply they can't manage users, or see all if root_admin style
                        stats['total_users'] = 0 # Or handle as an error case/restricted view
                elif user_role in ['member', 'viewer']: # Members/Viewers only count themselves if applicable
                    if session.get('id'):
                        stats['total_users'] = 1
                    else:
                        stats['total_users'] = 0 # Not logged in as a specific user
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
        if request.method == 'POST': 
            email = request.form.get('email')
            password = request.form.get('password')

            if not email or not password:
                msg = 'กรุณากรอกอีเมลและรหัสผ่านให้ครบถ้วน!'
                flash(msg, 'danger')
                return render_template('login.html', msg=msg)
            
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor(dictionary=True)
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
        print(f"Error during login: {err}") 
        msg = f"เกิดข้อผิดพลาดในการเข้าสู่ระบบ: {err}"
        flash(msg, 'danger')
    except Exception as e:
        print(f"An unexpected error occurred during login: {e}") 
        msg = f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}"
        flash(msg, 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return render_template('login.html', msg=msg)

@app.route('/logout')
def logout():
    """
    Logs out the user by clearing the session.
    """
    session.pop('loggedin', None)
    session.pop('id', None)
    session.pop('email', None)
    session.pop('firstname', None)
    session.pop('lastname', None)
    session.pop('role', None)
    session.pop('store_id', None)
    # Clear cart-related session variables upon logout
    session.pop('current_order_id', None)
    # session.pop('current_order_barcode', None) # No longer used as a session-wide barcode
    session.pop('receipt_data', None)
    flash('ออกจากระบบสำเร็จแล้ว!', 'success')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    Handles new user registration.
    Inserts new user data into tbl_users table with 'member' role by default.
    Checks for existing email addresses.
    Note: Members registered here will initially have NULL store_id.
    An administrator or root_admin needs to assign a store_id via the user management page.
    """
    msg = ''
    conn = None
    cursor = None
    try:
        if request.method == 'POST': 
            firstname = request.form.get('firstname')
            lastname = request.form.get('lastname')
            email = request.form.get('email')
            password = request.form.get('password')
            
            if not firstname or not lastname or not email or not password:
                flash('กรุณากรอกข้อมูลให้ครบถ้วน!', 'danger')
                return render_template('register.html', msg=msg) 

            conn = get_db_connection()
            if conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM tbl_users WHERE email = %s', (email,))
                account = cursor.fetchone()
                
                if account:
                    flash('บัญชีนี้มีอยู่แล้ว!', 'danger')
                elif not re.match(r'[^@]+@[^@]+\.[^@]+', email): # Added email format validation
                    flash('รูปแบบอีเมลไม่ถูกต้อง!', 'danger')
                else:
                    # Default role is 'member', store_id is NULL initially for public registration
                    cursor.execute('INSERT INTO tbl_users (firstname, lastname, email, password, role, store_id) VALUES (%s, %s, %s, %s, %s, %s)', 
                               (firstname, lastname, email, password, 'member', None)) # Explicitly set store_id to None
                    conn.commit()
                    flash('คุณสมัครสมาชิกสำเร็จแล้ว! โปรดให้ผู้ดูแลระบบกำหนดร้านค้าให้คุณหากจำเป็น', 'success') # Inform user
                    return redirect(url_for('login'))
        
    except mysql.connector.Error as err:
        print(f"Error during registration: {err}") 
        flash(f"เกิดข้อผิดพลาดในการสมัครสมาชิก: {err}", 'danger')
    except Exception as e:
        print(f"An unexpected error occurred during registration: {e}") 
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
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
        if request.method == 'POST': 
            if 'loggedin' in session:
                new_firstname = request.form.get('firstname')
                new_lastname = request.form.get('lastname')
                new_email = request.form.get('email')
                new_password = request.form.get('password') 

                if not new_firstname or not new_lastname or not new_email:
                    flash('กรุณากรอกชื่อ นามสกุล และอีเมลให้ครบถ้วน!', 'danger')
                    return render_template('profile.html', msg=msg, session=session) 

                conn = get_db_connection()
                if conn:
                    cursor = conn.cursor()
                    
                    # Check if the new email already exists for another user
                    cursor.execute('SELECT id FROM tbl_users WHERE email = %s AND id != %s', (new_email, session['id'],))
                    existing_email = cursor.fetchone()
                    if existing_email:
                        flash('อีเมลนี้มีผู้ใช้งานอื่นแล้ว!', 'danger')
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
                    flash('ข้อมูลโปรไฟล์ของคุณได้รับการอัปเดตสำเร็จ!', 'success')
                    return redirect(url_for('profile'))
            else:
                flash('โปรดเข้าสู่ระบบเพื่ออัปเดตโปรไฟล์ของคุณ', 'danger')
    except mysql.connector.Error as err:
        print(f"Error during profile update: {err}") 
        flash(f"เกิดข้อผิดพลาดในการอัปเดตโปรไฟล์: {err}", 'danger')
        if conn: conn.rollback()
    except Exception as e:
        print(f"An unexpected error occurred during profile update: {e}") 
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
        if conn: conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return render_template('profile.html', msg=msg, session=session)

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
            flash('กรุณากรอกข้อมูลสำหรับติดต่อให้ครบถ้วน!', 'danger')
            return render_template('contact.html', msg=msg)

        print(f"Contact Form: Name: {name}, Email: {email}, Subject: {subject}, Message: {message}")
        flash('ข้อความของคุณถูกส่งสำเร็จแล้ว!', 'success')
    return render_template('contact.html', msg=msg)

# --- Category Management ---
@app.route("/tbl_category", methods=["GET", "POST"])
@role_required(['root_admin', 'administrator', 'moderator', 'member', 'viewer']) # Allow members and viewers
def tbl_category():
    """
    Manages product categories (e.g., PET, Aluminum, Glass, Burnable, Contaminated Waste).
    Supports adding, editing, deleting, and searching categories.
    Members and Viewers can only view categories.
    Moderators and members can only see categories from their store.
    """
    msg = ''
    conn = None
    cursor = None
    categories = []
    stores = []
    search_query = request.args.get('search', '') # Get search from GET params for initial load/reset

    try:
        conn = get_db_connection()
        if not conn:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return render_template("tbl_category.html", categories=[], search=search_query, session=session, stores=[])

        cursor = conn.cursor(dictionary=True)
        
        current_user_role = session.get('role')
        current_user_store_id = session.get('store_id')

        # Fetch stores for category creation/editing (only for root_admin/admin)
        if current_user_role in ['root_admin', 'administrator']:
            store_query = "SELECT store_id, store_name FROM tbl_stores"
            store_params = []
            if current_user_role == 'administrator' and current_user_store_id:
                store_query += " WHERE store_id = %s"
                store_params.append(current_user_store_id)
            cursor.execute(store_query, tuple(store_params))
            stores = cursor.fetchall()

        can_modify = current_user_role in ['root_admin', 'administrator'] # Only root_admin and admin can modify

        if request.method == "POST":
            action = request.form.get('action')

            if action == 'add' and can_modify:
                category_name = request.form.get('category_name')
                store_id = request.form.get('store_id')

                if not category_name: 
                    flash('กรุณากรอกชื่อหมวดหมู่!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_category')) 
                
                if store_id: # Convert to int if not None
                    try:
                        store_id = int(store_id)
                    except ValueError:
                        flash('รหัสร้านค้าไม่ถูกต้อง!', 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_category'))
                else: 
                    store_id = None

                if current_user_role == 'administrator' and current_user_store_id:
                    if store_id is None or store_id != current_user_store_id:
                        flash('คุณไม่มีสิทธิ์เพิ่มหมวดหมู่นี้ในร้านค้าอื่น หรือต้องกำหนดร้านค้าให้ตรงกับร้านของคุณ', 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_category'))

                cursor.execute("INSERT INTO tbl_category (category_name, store_id) VALUES (%s, %s)", (category_name, store_id))
                conn.commit()
                flash('เพิ่มหมวดหมู่สำเร็จ!', 'success')
                return redirect(url_for('tbl_category')) # Redirect after action

            elif action == 'edit' and can_modify:
                cat_id = request.form.get('cat_id')
                category_name = request.form.get('category_name')
                store_id = request.form.get('store_id') 

                if not cat_id or not category_name: 
                    flash('กรุณากรอกข้อมูลหมวดหมู่เพื่อแก้ไขให้ครบถ้วน!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_category'))

                if store_id: 
                    try:
                        store_id = int(store_id)
                    except ValueError:
                        flash('รหัสร้านค้าไม่ถูกต้อง!', 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_category'))
                else:
                    store_id = None

                if current_user_role == 'administrator' and current_user_store_id:
                    cursor.execute("SELECT store_id FROM tbl_category WHERE id = %s", (cat_id,))
                    category_data = cursor.fetchone()
                    if category_data and category_data['store_id'] != current_user_store_id:
                        flash('คุณไม่มีสิทธิ์แก้ไขหมวดหมู่นี้', 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_category'))
                    
                    if store_id is None or store_id != current_user_store_id:
                        flash('คุณไม่มีสิทธิ์เปลี่ยนร้านค้าของหมวดหมู่ให้เป็นร้านอื่น หรือต้องกำหนดร้านค้าให้ตรงกับร้านของคุณ', 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_category'))

                cursor.execute("UPDATE tbl_category SET category_name = %s, store_id = %s WHERE id = %s", (category_name, store_id, cat_id))
                conn.commit()
                flash('อัปเดตหมวดหมู่สำเร็จ!', 'success')
                return redirect(url_for('tbl_category')) # Redirect after action

            elif action == 'delete' and can_modify:
                cat_id = request.form.get('cat_id')
                if not cat_id:
                    flash('ไม่พบรหัสหมวดหมู่ที่ต้องการลบ!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_category'))

                if current_user_role == 'administrator' and current_user_store_id:
                    cursor.execute("SELECT store_id FROM tbl_category WHERE id = %s", (cat_id,))
                    category_data = cursor.fetchone()
                    if category_data and category_data['store_id'] != current_user_store_id:
                        flash('คุณไม่มีสิทธิ์ลบหมวดหมู่นี้', 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_category'))

                cursor.execute("DELETE FROM tbl_category WHERE id = %s", (cat_id,))
                conn.commit()
                flash('ลบหมวดหมู่สำเร็จ!', 'success')
                return redirect(url_for('tbl_category')) # Redirect after action
            
            # For search action, update search_query from POST form if available
            if 'search' in request.form:
                search_query = request.form['search'] 
            
        # --- Data Fetching for Display (Common for both GET and non-redirecting POST) ---
        query = "SELECT c.id, c.category_name, c.store_id, s.store_name FROM tbl_category c LEFT JOIN tbl_stores s ON c.store_id = s.store_id"
        where_clauses = []
        query_params = []

        if current_user_role in ['moderator', 'member', 'viewer'] and current_user_store_id:
            where_clauses.append("c.store_id = %s")
            query_params.append(current_user_store_id)
        elif current_user_role == 'root_admin':
            pass 
        elif current_user_role == 'administrator' and current_user_store_id is None:
            pass 
        
        if search_query:
            search_clause = "(c.category_name LIKE %s OR c.id LIKE %s)"
            where_clauses.append(search_clause)
            query_params.extend(['%' + search_query + '%', '%' + search_query + '%'])

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        
        query += " ORDER BY c.id DESC"
        
        cursor.execute(query, tuple(query_params))
        categories = cursor.fetchall()

    except mysql.connector.Error as err:
        print(f"Error fetching categories: {err}") 
        flash(f"เกิดข้อผิดพลาดในการดึงหมวดหมู่: {err}", 'danger')
        if conn: conn.rollback()
        categories = [] # Ensure categories is empty on error
    except Exception as e:
        print(f"An unexpected error occurred: {e}") 
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
        if conn: conn.rollback()
        categories = [] # Ensure categories is empty on error
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    
    return render_template('tbl_category.html', categories=categories, search=search_query, msg=msg, session=session, stores=stores)


@app.route("/tbl_products", methods=["GET", "POST"])
@role_required(['root_admin', 'administrator', 'moderator', 'member', 'viewer']) # Allow members and viewers
def tbl_products():
    """
    Manages products.
    Supports adding, editing, deleting, and searching products.
    Members and Viewers can only view products.
    Moderators and members can only see products from their store.
    """
    msg = ''
    conn = None
    cursor = None
    products = []
    categories = []
    stores = [] 
    search_query = request.args.get('search', '') 

    try:
        conn = get_db_connection()
        if not conn:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return render_template("tbl_products.html", products=[], categories=[], search=search_query, session=session, stores=[])

        cursor = conn.cursor(dictionary=True)
        
        current_user_role = session.get('role')
        current_user_store_id = session.get('store_id')

        # Fetch categories for dropdown (filtered by store_id for relevant roles)
        category_query = "SELECT id, category_name FROM tbl_category"
        category_params = []
        if current_user_store_id: 
            category_query += " WHERE store_id = %s OR store_id IS NULL" 
            category_params.append(current_user_store_id)
        cursor.execute(category_query, tuple(category_params))
        categories = cursor.fetchall()

        # Fetch stores for product creation/editing (only for root_admin/admin)
        if current_user_role in ['root_admin', 'administrator']:
            store_query = "SELECT store_id, store_name FROM tbl_stores"
            store_params = []
            if current_user_role == 'administrator' and current_user_store_id:
                store_query += " WHERE store_id = %s"
                store_params.append(current_user_store_id)
            cursor.execute(store_query, tuple(store_params))
            stores = cursor.fetchall()


        can_modify = current_user_role in ['root_admin', 'administrator'] 

        if request.method == "POST":
            action = request.form.get('action')

            if action == 'add' and can_modify:
                products_name = request.form.get('products_name') 
                stock_quantity = request.form.get('stock_quantity') 
                price = request.form.get('price')
                category_id = request.form.get('category_id')
                barcode_id = request.form.get('barcode_id')
                store_id = request.form.get('store_id') 

                if not products_name or stock_quantity is None or price is None or not category_id or not barcode_id or not store_id:
                    flash('กรุณากรอกข้อมูลสินค้า (ชื่อ, สต็อก, ราคา, หมวดหมู่, บาร์โค้ด, ร้านค้า) ให้ครบถ้วน!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_products'))

                try:
                    stock_quantity = int(stock_quantity)
                    price = float(price)
                    category_id = int(category_id)
                    store_id = int(store_id)
                except ValueError:
                    flash('สต็อก, ราคา, หมวดหมู่ หรือ ร้านค้า ต้องเป็นตัวเลขที่ถูกต้อง!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_products'))
                
                if current_user_role == 'administrator' and current_user_store_id:
                    if store_id != current_user_store_id:
                        flash('คุณไม่มีสิทธิ์เพิ่มสินค้านี้ในร้านค้าอื่น หรือต้องกำหนดร้านค้าให้ตรงกับร้านของคุณ', 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_products'))

                cursor.execute("SELECT products_id FROM tbl_products WHERE barcode_id = %s AND store_id = %s", (barcode_id, store_id))
                existing_product_barcode = cursor.fetchone()
                if existing_product_barcode:
                    flash(f'รหัสบาร์โค้ด {barcode_id} มีอยู่แล้วในร้านค้านี้!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_products'))

                cursor.execute("INSERT INTO tbl_products (products_name, price, stock_quantity, category_id, barcode_id, store_id) VALUES (%s, %s, %s, %s, %s, %s)",
                               (products_name, price, stock_quantity, category_id, barcode_id, store_id))
                conn.commit()
                flash('เพิ่มสินค้าสำเร็จ!', 'success')
                return redirect(url_for('tbl_products')) # Redirect after action

            elif action == 'edit' and can_modify:
                products_id = request.form.get('products_id') 
                products_name = request.form.get('products_name')
                stock_quantity = request.form.get('stock_quantity')
                price = request.form.get('price')
                category_id = request.form.get('category_id')
                barcode_id = request.form.get('barcode_id')
                store_id = request.form.get('store_id') 

                if not products_id or not products_name or stock_quantity is None or price is None or not category_id or not barcode_id or not store_id:
                    flash('กรุณากรอกข้อมูลสินค้า (รหัสสินค้า, ชื่อ, สต็อก, ราคา, หมวดหมู่, บาร์โค้ด, ร้านค้า) เพื่อแก้ไขให้ครบถ้วน!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_products'))
                
                try:
                    products_id = int(products_id)
                    stock_quantity = int(stock_quantity)
                    price = float(price)
                    category_id = int(category_id)
                    store_id = int(store_id)
                except ValueError:
                    flash('รหัสสินค้า, สต็อก, ราคา, หมวดหมู่ หรือ ร้านค้า ต้องเป็นตัวเลขที่ถูกต้อง!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_products'))

                if current_user_role == 'administrator' and current_user_store_id:
                    cursor.execute("SELECT store_id FROM tbl_products WHERE products_id = %s", (products_id,))
                    product_data = cursor.fetchone()
                    if product_data and product_data['store_id'] != current_user_store_id:
                        flash('คุณไม่มีสิทธิ์แก้ไขสินค้านี้', 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_products'))

                    if store_id != current_user_store_id:
                        flash('คุณไม่มีสิทธิ์เปลี่ยนร้านค้าของสินค้า', 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_products'))

                cursor.execute("SELECT products_id FROM tbl_products WHERE barcode_id = %s AND store_id = %s AND products_id != %s", (barcode_id, store_id, products_id))
                existing_product = cursor.fetchone()
                if existing_product:
                    flash(f'รหัสบาร์โค้ด {barcode_id} มีอยู่แล้วในร้านค้านี้สำหรับสินค้าอื่น!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_products'))

                cursor.execute("UPDATE tbl_products SET products_name = %s, price = %s, stock_quantity = %s, category_id = %s, barcode_id = %s, store_id = %s WHERE products_id = %s",
                               (products_name, price, stock_quantity, category_id, barcode_id, store_id, products_id))
                conn.commit()
                flash('อัปเดตสินค้าสำเร็จ!', 'success')
                return redirect(url_for('tbl_products')) # Redirect after action

            elif action == 'delete' and can_modify:
                products_id = request.form.get('products_id') 
                if not products_id:
                    flash('ไม่พบรหัสสินค้าที่ต้องการลบ!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_products'))

                try:
                    products_id = int(products_id)
                except ValueError:
                    flash('รหัสสินค้าไม่ถูกต้อง!', 'danger')
                    return redirect(url_for('tbl_products'))

                if current_user_role == 'administrator' and current_user_store_id:
                    cursor.execute("SELECT store_id FROM tbl_products WHERE products_id = %s", (products_id,))
                    product_data = cursor.fetchone()
                    if product_data and product_data['store_id'] != current_user_store_id:
                        flash('คุณไม่มีสิทธิ์ลบสินค้านี้', 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_products'))

                cursor.execute("DELETE FROM tbl_products WHERE products_id = %s", (products_id,))
                conn.commit()
                flash('ลบสินค้าสำเร็จ!', 'success')
                return redirect(url_for('tbl_products')) # Redirect after action

            if 'search' in request.form:
                search_query = request.form['search']
            
        # --- Data Fetching for Display (Common for both GET and non-redirecting POST) ---
        product_query = """
            SELECT p.products_id, p.products_name, p.price, p.stock_quantity, c.category_name, p.barcode_id, p.store_id, s.store_name
            FROM tbl_products p
            LEFT JOIN tbl_category c ON p.category_id = c.id
            LEFT JOIN tbl_stores s ON p.store_id = s.store_id
        """
        product_where_clauses = []
        product_query_params = []

        if current_user_store_id:
            product_where_clauses.append("p.store_id = %s")
            product_query_params.append(current_user_store_id)
        elif current_user_role == 'root_admin' or (current_user_role == 'administrator' and current_user_store_id is None):
            pass 
        else:
            flash('คุณไม่มีสิทธิ์เข้าถึงสินค้า หรือร้านค้าของคุณไม่ถูกต้อง', 'danger')
            products = []
            if cursor: cursor.close()
            if conn: conn.close()
            return render_template('tbl_products.html', products=products, categories=categories, search=search_query, session=session, stores=stores)

        if search_query:
            search_clause = "(p.products_name LIKE %s OR p.products_id LIKE %s OR c.category_name LIKE %s OR p.barcode_id LIKE %s)"
            if not product_query_params: 
                product_where_clauses.append(search_clause)
            else: 
                product_where_clauses.append(search_clause)
            product_query_params.extend(['%' + search_query + '%', '%' + search_query + '%', '%' + search_query + '%', '%' + search_query + '%'])

        if product_where_clauses:
            product_query += " WHERE " + " AND ".join(product_where_clauses)
        
        product_query += " ORDER BY p.products_id DESC"
        
        cursor.execute(product_query, tuple(product_query_params))
        products = cursor.fetchall()

    except mysql.connector.Error as err:
        print(f"Error fetching products: {err}") 
        flash(f"เกิดข้อผิดพลาดในการดึงสินค้า: {err}", 'danger')
        if conn: conn.rollback()
        products = [] # Ensure products is empty on error
    except Exception as e:
        print(f"An unexpected error occurred: {e}") 
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
        if conn: conn.rollback()
        products = [] # Ensure products is empty on error
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return render_template('tbl_products.html', products=products, categories=categories, search=search_query, msg=msg, session=session, stores=stores)
   
   
# --- Order Management ---

@app.route("/tbl_order", methods=["GET", "POST"])
@role_required(['root_admin', 'administrator', 'moderator', 'member', 'viewer'])
def tbl_order():
    """
    Manages customer orders, including quantity tracking and disposed quantity.
    Supports adding, editing, deleting, and searching orders.
    Stock is updated based on ordered quantity.
    Members and Viewers can only view orders.
    Moderators and Members can only view orders within their store.
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

        current_user_role = session.get('role')
        current_user_store_id = session.get('store_id')

        # Fetch products for the product dropdowns in modals (filtered by store_id for relevant roles)
        product_query_for_dropdown = "SELECT products_id, products_name, stock_quantity as stock, price FROM tbl_products"
        product_dropdown_params = []
        if current_user_store_id:
            product_query_for_dropdown += " WHERE store_id = %s OR store_id IS NULL" 
            product_dropdown_params.append(current_user_store_id)
        product_query_for_dropdown += " ORDER BY products_name"

        cursor.execute(product_query_for_dropdown, tuple(product_dropdown_params))
        products_data = cursor.fetchall()

        # Fetch users for the email dropdown in modals (if admin/moderator, filtered by store_id)
        if current_user_role in ['root_admin', 'administrator', 'moderator']:
            user_query_for_dropdown = "SELECT email, CONCAT(firstname, ' ', lastname) as fullname FROM tbl_users"
            user_dropdown_params = []
            if current_user_store_id:
                user_query_for_dropdown += " WHERE store_id = %s OR store_id IS NULL" 
                user_dropdown_params.append(current_user_store_id)
            user_query_for_dropdown += " ORDER BY firstname"
            cursor.execute(user_query_for_dropdown, tuple(user_dropdown_params))
            users_data = cursor.fetchall()

        can_modify = current_user_role in ['root_admin', 'administrator', 'moderator']

        if request.method == "POST":
            action = request.form.get('action')

            if action == 'add' and can_modify:
                order_id = request.form.get('order_id')
                products_id = request.form.get('products_id')
                quantity_str = request.form.get('quantity')
                disquantity_str = request.form.get('disquantity')
                barcode_id = request.form.get('barcode_id', None) 
                
                email = request.form.get('email') if current_user_role in ['root_admin', 'administrator', 'moderator'] else session.get('email')

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

                product_check_query = "SELECT products_name, stock_quantity, price, category_id, store_id FROM tbl_products WHERE products_id = %s"
                product_check_params = [products_id]
                
                if current_user_store_id:
                    product_check_query += " AND (store_id = %s OR store_id IS NULL)"
                    product_check_params.append(current_user_store_id)

                cursor.execute(product_check_query, tuple(product_check_params))
                product_info = cursor.fetchone()

                if not product_info:
                    flash("ไม่พบสินค้าที่เลือกหรือสินค้าไม่ได้อยู่ในร้านค้าของคุณ!", 'danger')
                    return redirect(url_for('tbl_order'))
                
                if quantity > product_info['stock_quantity']:
                    flash(f"สินค้า {product_info['products_name']} มีสต็อกไม่พอ. มีในสต็อก: {product_info['stock_quantity']}", 'danger')
                    return redirect(url_for('tbl_order'))
                
                product_store_id = product_info['store_id'] if product_info['store_id'] is not None else current_user_store_id 

                cursor.execute("SELECT id FROM tbl_order WHERE order_id = %s AND products_id = %s AND store_id = %s", (order_id, products_id, product_store_id))
                existing_order_item = cursor.fetchone()
                if existing_order_item:
                    flash(f"รายการสินค้านี้ (Products ID: {products_id}) มีอยู่ในคำสั่งซื้อ {order_id} แล้วสำหรับร้านค้านี้. โปรดแก้ไขรายการเดิมแทน.", 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_order'))

                insert_query = """
                    INSERT INTO tbl_order (order_id, email, products_id, quantity, disquantity, store_id, order_date, price_per_unit, barcode_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(insert_query, (order_id, email, products_id, quantity, disquantity, product_store_id, datetime.now(), product_info['price'], barcode_id))
                
                update_stock_query = "UPDATE tbl_products SET stock_quantity = stock_quantity - %s WHERE products_id = %s"
                cursor.execute(update_stock_query, (quantity, products_id))
                
                if disquantity > 0:
                    cursor.execute("UPDATE tbl_bin SET value = 1 WHERE category_id = %s AND store_id = %s", (product_info['category_id'], product_store_id))

                conn.commit()
                flash('เพิ่มคำสั่งซื้อสำเร็จและอัปเดตสต็อกสินค้าแล้ว!', 'success')
                return redirect(url_for('tbl_order')) 
            
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

                order_check_query = "SELECT products_id, quantity, disquantity, store_id, email FROM tbl_order WHERE id = %s"
                order_check_params = [ord_id]

                if current_user_role in ['moderator', 'member'] and current_user_store_id:
                    order_check_query += " AND store_id = %s"
                    order_check_params.append(current_user_store_id)
                elif current_user_role == 'member': 
                    order_check_query += " AND email = %s"
                    order_check_params.append(session.get('email'))

                cursor.execute(order_check_query, tuple(order_check_params))
                old_order_info = cursor.fetchone()

                if not old_order_info:
                    flash("ไม่พบคำสั่งซื้อที่ต้องการแก้ไข หรือคุณไม่มีสิทธิ์แก้ไขรายการนี้!", 'danger')
                    return redirect(url_for('tbl_order'))
                
                old_products_id = old_order_info['products_id']
                old_quantity = old_order_info['quantity']
                old_disquantity = old_order_info['disquantity']
                order_item_store_id = old_order_info['store_id'] 

                new_product_check_query = "SELECT products_name, stock_quantity, category_id FROM tbl_products WHERE products_id = %s"
                new_product_check_params = [products_id]
                if current_user_store_id: 
                    new_product_check_query += " AND (store_id = %s OR store_id IS NULL)"
                    new_product_check_params.append(current_user_store_id)
                
                cursor.execute(new_product_check_query, tuple(new_product_check_params))
                new_product_info = cursor.fetchone()

                if not new_product_info:
                    flash("ไม่พบสินค้าใหม่ที่เลือก หรือสินค้าไม่ได้อยู่ในร้านค้าของคุณ!", 'danger')
                    return redirect(url_for('tbl_order'))
                
                products_name = new_product_info['products_name']
                current_stock_of_new_product = new_product_info['stock_quantity']
                category_id_of_new_product = new_product_info['category_id']


                if products_id != old_products_id:
                    cursor.execute("UPDATE tbl_products SET stock_quantity = stock_quantity + %s WHERE products_id = %s", (old_quantity, old_products_id))
                    
                    if quantity > current_stock_of_new_product:
                        flash(f"สินค้า {products_name} มีสต็อกไม่พอสำหรับการสั่งซื้อใหม่. มีในสต็อก: {current_stock_of_new_product}", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_order'))
                    cursor.execute("UPDATE tbl_products SET stock_quantity = stock_quantity - %s WHERE products_id = %s", (quantity, products_id))
                else:
                    quantity_difference = quantity - old_quantity
                    if current_stock_of_new_product - quantity_difference < 0:
                        flash(f"สินค้า {products_name} มีสต็อกไม่พอสำหรับการเปลี่ยนแปลงจำนวน. มีในสต็อก: {current_stock_of_new_product}", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_order'))
                    cursor.execute("UPDATE tbl_products SET stock_quantity = stock_quantity - %s WHERE products_id = %s", (quantity_difference, products_id))
                
                cursor.execute("""
                    UPDATE tbl_order SET order_id = %s, products_id = %s, products_name = %s, quantity = %s, disquantity = %s, email = %s, barcode_id = %s
                    WHERE id = %s
                """, (order_id, products_id, products_name, quantity, disquantity, email, barcode_id, ord_id))

                if disquantity > 0: 
                    cursor.execute("UPDATE tbl_bin SET value = 1 WHERE category_id = %s AND store_id = %s", (category_id_of_new_product, order_item_store_id))
                elif disquantity == 0 and old_disquantity > 0: 
                    cursor.execute("""
                        SELECT COUNT(*) FROM tbl_order o 
                        JOIN tbl_products p ON o.products_id = p.products_id 
                        WHERE p.category_id = %s AND o.disquantity > 0 AND o.store_id = %s AND o.id != %s
                    """, (category_id_of_new_product, order_item_store_id, ord_id))
                    remaining_disposed_in_category_in_store = cursor.fetchone()[0]
                    if remaining_disposed_in_category_in_store == 0:
                        cursor.execute("UPDATE tbl_bin SET value = 0 WHERE category_id = %s AND store_id = %s", (category_id_of_new_product, order_item_store_id))

                conn.commit()
                flash('อัปเดตคำสั่งซื้อสำเร็จและอัปเดตสต็อกสินค้าแล้ว!', 'success')
                return redirect(url_for('tbl_order')) 

            elif action == 'delete' and can_modify:
                ord_id = request.form.get('ord_id')
                if not ord_id:
                    flash('ไม่พบรหัสคำสั่งซื้อที่ต้องการลบ!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_order'))
                
                order_to_delete_query = "SELECT products_id, quantity, store_id, email FROM tbl_order WHERE id = %s"
                order_to_delete_params = [ord_id]

                if current_user_role in ['moderator', 'member'] and current_user_store_id:
                    order_to_delete_query += " AND store_id = %s"
                    order_to_delete_params.append(current_user_store_id)
                elif current_user_role == 'member': 
                    order_to_delete_query += " AND email = %s"
                    order_to_delete_params.append(session.get('email'))
                
                cursor.execute(order_to_delete_query, tuple(order_to_delete_params))
                order_to_delete = cursor.fetchone()

                if not order_to_delete:
                    flash("ไม่พบคำสั่งซื้อที่ต้องการลบ หรือคุณไม่มีสิทธิ์ลบรายการนี้!", 'danger')
                    return redirect(url_for('tbl_order'))
                
                product_id_to_restore = order_to_delete['products_id']
                quantity_to_restore = order_to_delete['quantity']
                order_item_store_id = order_to_delete['store_id']

                cursor.execute("DELETE FROM tbl_order WHERE id = %s", (ord_id,))

                cursor.execute("UPDATE tbl_products SET stock_quantity = stock_quantity + %s WHERE products_id = %s", (quantity_to_restore, product_id_to_restore))

                cursor.execute("""
                    SELECT COUNT(*) FROM tbl_order o 
                    JOIN tbl_products p ON o.products_id = p.products_id 
                    WHERE o.disquantity > 0 AND p.category_id = (SELECT category_id FROM tbl_products WHERE products_id = %s) AND o.store_id = %s
                """, (product_id_to_restore, order_item_store_id))
                remaining_disposed_for_category = cursor.fetchone()[0]

                if remaining_disposed_for_category == 0:
                    cursor.execute("UPDATE tbl_bin SET value = 0 WHERE category_id = (SELECT category_id FROM tbl_products WHERE products_id = %s) AND store_id = %s", (product_id_to_restore, order_item_store_id))

                conn.commit()
                flash('ลบคำสั่งซื้อสำเร็จและคืนสต็อกสินค้าแล้ว!', 'success')
                return redirect(url_for('tbl_order')) 

            if 'search' in request.form:
                search_query = request.form['search']
            
        # --- Data Fetching for Display (Common for both GET and non-redirecting POST) ---
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
                o.price_per_unit as price, 
                o.store_id,
                s.store_name
            FROM tbl_order o
            LEFT JOIN tbl_products p ON o.products_id = p.products_id
            LEFT JOIN tbl_users u ON o.email = u.email
            LEFT JOIN tbl_stores s ON o.store_id = s.store_id
        """
        query_params = []
        where_clauses = []

        if current_user_store_id:
            if current_user_role == 'member': 
                where_clauses.append("o.email = %s AND o.store_id = %s") 
                query_params.extend([session['email'], current_user_store_id])
            elif current_user_role in ['administrator', 'moderator', 'viewer']: 
                where_clauses.append("o.store_id = %s")
                query_params.append(current_user_store_id)
        elif current_user_role == 'root_admin':
            pass 

        if search_query:
            search_clause = "(o.order_id LIKE %s OR o.products_name LIKE %s OR o.email LIKE %s)"
            if not where_clauses: 
                where_clauses.append(search_clause)
            else: 
                where_clauses.append(f"({search_clause})") 
            query_params.extend(['%' + search_query + '%'] * 3)

        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)

        base_query += " ORDER BY o.id DESC"
        
        cursor.execute(base_query, tuple(query_params))
        orders = cursor.fetchall()

    except mysql.connector.Error as err:
        print(f"Error in tbl_order: {err}") 
        flash(f"เกิดข้อผิดพลาดในฐานข้อมูล: {err}", 'danger')
        if conn: conn.rollback()
        orders = [] # Ensure orders is empty on error
    except Exception as e:
        print(f"An unexpected error occurred in tbl_order: {e}") 
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
        if conn: conn.rollback()
        orders = [] # Ensure orders is empty on error
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

        # Fetch all stores for dropdown (filtered by current_user_role)
        store_query = "SELECT store_id, store_name FROM tbl_stores ORDER BY store_name"
        store_params = []
        if session.get('role') == 'administrator' and session.get('store_id'):
            store_query += " WHERE store_id = %s"
            store_params.append(session['store_id'])
        cursor.execute(store_query, tuple(store_params))
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
                
                new_user_role = request.form.get('role') 
                new_user_store_id = request.form.get('store_id') 

                if not firstname or not lastname or not email or not password or not new_user_role:
                    flash('กรุณากรอกข้อมูลผู้ใช้งาน (ชื่อ, นามสกุล, อีเมล, รหัสผ่าน, บทบาท) ให้ครบถ้วน!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))

                if new_user_store_id:
                    try:
                        new_user_store_id = int(new_user_store_id)
                    except ValueError:
                        new_user_store_id = None 
                else:
                    new_user_store_id = None

                permission_granted_for_add = False
                if current_user_role == 'root_admin':
                    permission_granted_for_add = True
                elif current_user_role == 'administrator':
                    if new_user_role == 'root_admin':
                        flash("คุณไม่มีสิทธิ์เพิ่มผู้ใช้งาน Root Admin!", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    
                    if current_user_store_id:
                        if new_user_store_id is not None and new_user_store_id != current_user_store_id:
                            flash("Administrator สามารถเพิ่มผู้ใช้ได้เฉพาะในร้านค้าของตนเองเท่านั้น", 'danger')
                            conn.rollback()
                            return redirect(url_for('tbl_users'))
                        new_user_store_id = current_user_store_id 
                    
                    permission_granted_for_add = True

                elif current_user_role == 'moderator':
                    if new_user_role != 'member': 
                        flash("Moderator สามารถเพิ่มได้เฉพาะผู้ใช้งานยศ 'member' เท่านั้น!", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    
                    if not current_user_store_id:
                        flash("Moderator ของคุณไม่ได้ถูกกำหนดร้านค้า ไม่สามารถเพิ่มผู้ใช้งานได้.", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    
                    new_user_role = 'member'
                    new_user_store_id = current_user_store_id
                    permission_granted_for_add = True
                    
                if not permission_granted_for_add:
                    flash("คุณไม่มีสิทธิ์เพิ่มผู้ใช้งานด้วยบทบาทนี้.", 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))

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
                return redirect(url_for('tbl_users')) # Redirect after action

            elif action == 'edit':
                user_id = request.form.get('user_id')
                firstname = request.form.get('firstname')
                lastname = request.form.get('lastname')
                email = request.form.get('email')
                password = request.form.get('password') if request.form.get('password') else None
                
                submitted_role = request.form.get('role')
                submitted_store_id = request.form.get('store_id')

                if not user_id or not firstname or not lastname or not email:
                    flash('กรุณากรอกข้อมูลผู้ใช้งานเพื่อแก้ไข (ชื่อ, นามสกุล, อีเมล) ให้ครบถ้วน!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))

                if submitted_store_id:
                    try:
                        submitted_store_id = int(submitted_store_id)
                    except ValueError:
                        submitted_store_id = None
                else:
                    submitted_store_id = None


                cursor.execute("SELECT role, store_id FROM tbl_users WHERE id = %s", (user_id,))
                target_user_data = cursor.fetchone()
                if not target_user_data:
                    flash("ไม่พบผู้ใช้งานที่ต้องการแก้ไข.", 'danger')
                    conn.rollback() 
                    return redirect(url_for('tbl_users'))
                
                target_user_role = target_user_data['role']
                target_user_store_id = target_user_data['store_id']

                effective_role = target_user_role 
                effective_store_id = target_user_store_id 

                permission_granted_for_edit = False
                if current_user_role == 'root_admin':
                    if target_user_role == 'root_admin' and submitted_role != 'root_admin' and str(user_id) == str(session['id']):
                        flash("คุณไม่สามารถเปลี่ยนยศของ Root Admin ที่เข้าสู่ระบบอยู่ได้", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    
                    effective_role = submitted_role
                    effective_store_id = submitted_store_id
                    permission_granted_for_edit = True

                elif current_user_role == 'administrator':
                    if target_user_role == 'root_admin':
                        flash("คุณไม่มีสิทธิ์แก้ไขผู้ใช้งาน Root Admin.", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    
                    if submitted_role == 'root_admin':
                        flash("คุณไม่มีสิทธิ์กำหนดให้ผู้ใช้งานเป็น Root Admin.", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))
                    
                    if current_user_store_id:
                        if target_user_store_id != current_user_store_id:
                            flash("Administrator สามารถแก้ไขผู้ใช้ได้เฉพาะในร้านค้าของตนเองเท่านั้น", 'danger')
                            conn.rollback()
                            return redirect(url_for('tbl_users'))
                        
                        if submitted_store_id is not None and submitted_store_id != current_user_store_id:
                            flash("Administrator ไม่สามารถเปลี่ยนร้านค้าของผู้ใช้งานที่แก้ไขได้", 'danger')
                            conn.rollback()
                            return redirect(url_for('tbl_users'))
                        effective_store_id = current_user_store_id 
                    
                    effective_role = submitted_role 
                    if submitted_store_id is None: 
                         effective_store_id = None
                    elif current_user_store_id and submitted_store_id == current_user_store_id: 
                        effective_store_id = submitted_store_id
                    elif not current_user_store_id: 
                        effective_store_id = submitted_store_id


                    permission_granted_for_edit = True

                elif current_user_role == 'moderator':
                    if target_user_role != 'member' or target_user_store_id != current_user_store_id:
                        flash("Moderator สามารถแก้ไขได้เฉพาะผู้ใช้งานยศ 'member' ในร้านค้าของตนเองเท่านั้น.", 'danger')
                        conn.rollback()
                        return redirect(url_for('tbl_users'))

                    effective_role = target_user_role 
                    effective_store_id = target_user_store_id 
                    
                    permission_granted_for_edit = True

                if not permission_granted_for_edit:
                    flash("คุณไม่มีสิทธิ์แก้ไขผู้ใช้งานรายนี้.", 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))

                cursor.execute('SELECT id FROM tbl_users WHERE email = %s AND id != %s', (email, user_id,))
                existing_email = cursor.fetchone()
                if existing_email:
                    flash('อีเมลนี้มีผู้ใช้งานอื่นแล้ว!', 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))

                if password:
                    sql_update = 'UPDATE tbl_users SET firstname = %s, lastname = %s, email = %s, password = %s, role = %s, store_id = %s WHERE id = %s'
                    cursor.execute(sql_update, (firstname, lastname, email, password, effective_role, effective_store_id, user_id))
                else:
                    sql_update = 'UPDATE tbl_users SET firstname = %s, lastname = %s, email = %s, role = %s, store_id = %s WHERE id = %s'
                    cursor.execute(sql_update, (firstname, lastname, email, effective_role, effective_store_id, user_id))
                
                conn.commit()
                flash('อัปเดตผู้ใช้งานสำเร็จ!', 'success')
                return redirect(url_for('tbl_users')) # Redirect after action

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
                    if target_user_role == 'root_admin': 
                        flash("คุณไม่มีสิทธิ์ลบผู้ใช้งาน Root Admin.", 'danger')
                        return redirect(url_for('tbl_users'))
                    
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
                return redirect(url_for('tbl_users')) # Redirect after action
            
            if 'search' in request.form:
                search_query = request.form['search']
            
        # --- Data Fetching for Display (Common for both GET and non-redirecting POST) ---
        sql_select = """
            SELECT u.id, u.firstname, u.lastname, u.email, u.role, u.store_id, s.store_name
            FROM tbl_users u
            LEFT JOIN tbl_stores s ON u.store_id = s.store_id
        """
        params = []
        where_clauses = []

        if current_user_role == 'root_admin':
            if search_query:
                where_clauses.append("(u.firstname LIKE %s OR u.lastname LIKE %s OR u.email LIKE %s OR u.role LIKE %s OR s.store_name LIKE %s)")
                params.extend(['%' + search_query + '%'] * 5)
        elif current_user_role in ['administrator', 'moderator']:
            if current_user_store_id:
                where_clauses.append("u.store_id = %s")
                params.append(current_user_store_id)
                if search_query:
                    where_clauses.append("(u.firstname LIKE %s OR u.lastname LIKE %s OR u.email LIKE %s OR u.role LIKE %s)")
                    params.extend(['%' + search_query + '%'] * 4)
            else:
                flash("คุณไม่ได้ถูกกำหนดร้านค้า จึงไม่สามารถดูข้อมูลผู้ใช้งานได้.", 'danger')
                users = []
                if cursor: cursor.close()
                if conn: conn.close()
                return render_template("tbl_users.html", users=users, search=search_query, stores=stores) 

        if where_clauses:
            sql_select += " WHERE " + " AND ".join(where_clauses)
        
        sql_select += " ORDER BY u.id DESC"

        cursor.execute(sql_select, tuple(params))
        users = cursor.fetchall()
        
    except mysql.connector.Error as err:
        print(f"Error in tbl_users: {err}") 
        flash(f"เกิดข้อผิดพลาดในฐานข้อมูล: {err}", 'danger')
        if conn: conn.rollback()
        users = [] # Ensure users is empty on error
    except Exception as e:
        print(f"An unexpected error occurred: {e}") 
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
        if conn: conn.rollback()
        users = [] # Ensure users is empty on error
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
        
        current_user_role = session.get('role')
        current_user_store_id = session.get('store_id')

        if store_id:
            try:
                store_id = int(store_id)
            except ValueError:
                store_id = None 
        else: 
            store_id = None

        if not user_id: 
            flash("ไม่พบรหัสผู้ใช้งานที่ต้องการกำหนดร้านค้า.", 'danger')
            return redirect(url_for('tbl_users'))

        conn = get_db_connection()
        if not conn:
            flash("ไม่สามารถเชื่อมต่อฐานข้อมูลได้.", 'danger')
            return redirect(url_for('tbl_users'))

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
            if target_user_role == 'root_admin':
                flash("คุณไม่มีสิทธิ์กำหนดร้านค้าให้ผู้ใช้งาน Root Admin.", 'danger')
                conn.rollback()
                return redirect(url_for('tbl_users'))
            
            if current_user_store_id:
                if target_user_store_id is not None and target_user_store_id != current_user_store_id:
                    flash("Administrator สามารถกำหนดร้านค้าให้ผู้ใช้ได้เฉพาะในร้านค้าของตนเองเท่านั้น", 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))
                
                if store_id is not None and store_id != current_user_store_id:
                    flash("Administrator ไม่สามารถกำหนดร้านค้าให้ผู้ใช้นอกร้านค้าของตนเองได้", 'danger')
                    conn.rollback()
                    return redirect(url_for('tbl_users'))
                
                if target_user_store_id is None and store_id == current_user_store_id:
                    permission_granted = True
                elif target_user_store_id == current_user_store_id:
                    permission_granted = True
                else: 
                     flash("Administrator ไม่มีสิทธิ์กำหนดร้านค้าแบบนี้.", 'danger')
                     conn.rollback()
                     return redirect(url_for('tbl_users'))
            else: 
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
    except mysql.connector.Error as err:
        print(f"Error assigning store: {err}") 
        flash(f"เกิดข้อผิดพลาดในการกำหนดร้านค้า: {err}", 'danger')
        if conn: conn.rollback()
    except Exception as e:
        print(f"An unexpected error occurred: {e}") 
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
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
@role_required(['root_admin', 'administrator', 'moderator'])
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

        current_user_store_id = session.get('store_id')
        product_check_query = "SELECT products_name FROM tbl_products WHERE products_id = %s"
        product_check_params = [product_id]
        if current_user_store_id: 
            product_check_query += " AND (store_id = %s OR store_id IS NULL)" 
            product_check_params.append(current_user_store_id)
        
        cursor.execute(product_check_query, tuple(product_check_params))
        product_exists = cursor.fetchone()
        if not product_exists:
            flash("ไม่พบรหัสสินค้านี้ในร้านค้าของคุณ หรือคุณไม่มีสิทธิ์สร้างบาร์โค้ดสำหรับสินค้านี้.", 'danger')
            return redirect(url_for('tbl_products'))

        encoded_id = encode(int(product_id))
        barcode_value = str(encoded_id).zfill(13) 


        width, height = 300, 100
        image = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(image)

        try:
            font_path = "arial.ttf" 
            font_size = 20 
            font = ImageFont.truetype(font_path, font_size)
        except IOError:
            font = ImageFont.load_default()
            print("Warning: Custom font not found. Using default font.")

        bar_width = 2
        bar_height = 50
        total_bar_width = len(barcode_value) * bar_width * 2 
        start_x = (width - total_bar_width) / 2
        if start_x < 0: start_x = 0 

        for i, digit_char in enumerate(barcode_value):
            x0 = start_x + i * bar_width * 2
            x1 = x0 + bar_width
            if digit_char == '0':
                pass 
            else: 
                draw.rectangle([(x0, 10), (x1, 10 + bar_height)], fill='black')
        
        text_display = f"ID: {product_id} | Barcode: {barcode_value}"
        
        text_bbox = draw.textbbox((0,0), text_display, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        text_x = (width - text_width) / 2
        text_y = 10 + bar_height + 5 

        draw.text((text_x, text_y), text_display, fill='black', font=font)

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
    """Exports product data to a CSV file. Filters by store_id for relevant roles."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return redirect(url_for('tbl_products'))
        
        cursor = conn.cursor(dictionary=True)
        
        current_user_role = session.get('role')
        current_user_store_id = session.get('store_id')

        product_query = "SELECT products_id, products_name, stock_quantity, price, category_id, barcode_id, store_id FROM tbl_products"
        product_params = []
        if current_user_store_id: 
            product_query += " WHERE store_id = %s"
            product_params.append(current_user_store_id)

        cursor.execute(product_query, tuple(product_params))
        products = cursor.fetchall()
        
        si = StringIO()
        cw = csv.writer(si)
        
        cw.writerow(['Product ID', 'Product Name', 'Stock Quantity', 'Price', 'Category ID', 'Barcode ID', 'Store ID'])
        
        for product in products:
            cw.writerow([product['products_id'], product['products_name'], product['stock_quantity'], product['price'], product['category_id'], product['barcode_id'], product['store_id']])
        
        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = "attachment; filename=products_report.csv"
        output.headers["Content-type"] = "text/csv"
        return output
    except mysql.connector.Error as err:
        print(f"Error exporting products CSV: {err}") 
        flash(f"เกิดข้อผิดพลาดในการส่งออกข้อมูลสินค้า: {err}", 'danger')
        if conn: conn.rollback()
        return redirect(url_for('tbl_products'))
    except Exception as e:
        print(f"An unexpected error occurred during CSV export: {e}") 
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
    """Exports order data to a PDF file. Filters by store_id for relevant roles."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return redirect(url_for('tbl_order'))

        cursor = conn.cursor(dictionary=True)
        current_user_role = session.get('role')
        current_user_store_id = session.get('store_id')

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
                o.price_per_unit as price, 
                o.store_id,
                s.store_name
            FROM tbl_order o
            LEFT JOIN tbl_products p ON o.products_id = p.products_id
            LEFT JOIN tbl_users u ON o.email = u.email
            LEFT JOIN tbl_stores s ON o.store_id = s.store_id
        """
        query_params = []
        where_clauses = []

        if current_user_store_id:
            if current_user_role == 'member':
                where_clauses.append("o.email = %s AND o.store_id = %s")
                query_params.extend([session['email'], current_user_store_id])
            elif current_user_role in ['administrator', 'moderator', 'viewer']:
                where_clauses.append("o.store_id = %s")
                query_params.append(current_user_store_id)
        elif current_user_role == 'root_admin':
            pass 

        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)
        
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
        print(f"Error exporting orders PDF: {err}") 
        flash(f"เกิดข้อผิดพลาดในการส่งออกรายงานคำสั่งซื้อ: {err}", 'danger')
        if conn: conn.rollback()
        return redirect(url_for('tbl_order'))
    except Exception as e:
        print(f"An unexpected error occurred during PDF export: {e}") 
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
    """Exports order data to a CSV file. Filters by store_id for relevant roles."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            flash("ไม่สามารถเชื่อมต่อฐานข้อมูล.", 'danger')
            return redirect(url_for('tbl_order'))

        cursor = conn.cursor(dictionary=True)
        current_user_role = session.get('role')
        current_user_store_id = session.get('store_id')

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
                o.price_per_unit as price, 
                o.store_id,
                s.store_name
            FROM tbl_order o
            LEFT JOIN tbl_products p ON o.products_id = p.products_id
            LEFT JOIN tbl_users u ON o.email = u.email
            LEFT JOIN tbl_stores s ON o.store_id = s.store_id
        """
        query_params = []
        where_clauses = []

        if current_user_store_id:
            if current_user_role == 'member':
                where_clauses.append("o.email = %s AND o.store_id = %s")
                query_params.extend([session['email'], current_user_store_id])
            elif current_user_role in ['administrator', 'moderator', 'viewer']:
                where_clauses.append("o.store_id = %s")
                query_params.append(current_user_store_id)
        elif current_user_role == 'root_admin':
            pass 

        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)
        
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
        print(f"Error exporting orders CSV: {err}") 
        flash(f"เกิดข้อผิดพลาดในการส่งออกรายงานคำสั่งซื้อ: {err}", 'danger')
        if conn: conn.rollback()
    except Exception as e:
        print(f"An unexpected error occurred during CSV export: {e}") 
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
    request_form_data = {}

    current_user_role = session.get('role')
    current_user_store_id = session.get('store_id')

    try:
        conn = get_db_connection()
        if not conn:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return render_template("cart.html", orders=[], products_data_string='', users=[], search='',
                                   current_auto_order_id='', selected_product_details_display='เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล',
                                   pre_filled_products_id_input='', session=session)

        cursor = conn.cursor(dictionary=True)

        if not current_auto_order_id:
            if current_user_store_id:
                cursor.execute("SELECT MAX(CAST(order_id AS UNSIGNED)) AS max_order_id FROM tbl_order WHERE order_id REGEXP '^[0-9]+$' AND store_id = %s", (current_user_store_id,))
            else: 
                cursor.execute("SELECT MAX(CAST(order_id AS UNSIGNED)) AS max_order_id FROM tbl_order WHERE order_id REGEXP '^[0-9]+$'")
            
            result = cursor.fetchone()
            current_order_id = str(int(result['max_order_id']) + 1) if result and result['max_order_id'] is not None else '100001'
            session['current_order_id'] = current_order_id
        
        product_query_for_frontend = "SELECT products_id, products_name, stock_quantity as stock, price, barcode_id FROM tbl_products"
        product_frontend_params = []
        if current_user_store_id:
            product_query_for_frontend += " WHERE store_id = %s OR store_id IS NULL" 
            product_frontend_params.append(current_user_store_id)
        product_query_for_frontend += " ORDER BY products_id"

        cursor.execute(product_query_for_frontend, tuple(product_frontend_params))
        products_data = cursor.fetchall()
        products_data_parts = [f"{p['products_id']}|{str(p['products_name']).replace('|', ' ').replace('///', ' ')}|{p['stock']}|{p['price']}|{str(p.get('barcode_id') or '').replace('|', ' ').replace('///', ' ')}" for p in products_data]
        products_data_string = "///".join(products_data_parts)
        
        if current_user_role in ['root_admin', 'administrator', 'moderator']:
            user_query_for_frontend = "SELECT email, CONCAT(firstname, ' ', lastname) as fullname FROM tbl_users"
            user_frontend_params = []
            if current_user_store_id:
                user_query_for_frontend += " WHERE store_id = %s OR store_id IS NULL" 
                user_frontend_params.append(current_user_store_id)
            user_query_for_frontend += " ORDER BY firstname"
            cursor.execute(user_query_for_frontend, tuple(user_frontend_params))
            users_data = cursor.fetchall()

        if request.method == "POST":
            request_form_data = request.form.to_dict() 
            action = request.form.get('action')

            if action == 'complete_order':
                cursor.execute("""
                    SELECT o.*, p.price, p.products_name
                    FROM tbl_order o
                    JOIN tbl_products p ON o.products_id = p.products_id
                    WHERE o.order_id = %s AND o.store_id = %s AND o.email = %s
                    ORDER BY o.id
                """, (current_order_id, current_user_store_id, session.get('email'))) 
                orders_to_complete = cursor.fetchall()
                
                if not orders_to_complete:
                    flash('ไม่พบรายการสินค้าในคำสั่งซื้อนี้.', 'danger')
                    return redirect(url_for('cart'))

                total_quantity = sum(item['quantity'] for item in orders_to_complete)
                total_price = sum(item['quantity'] * item['price_per_unit'] for item in orders_to_complete) 
                
                receipt_barcode = ''.join(random.choices(string.digits, k=13)) 
                
                session['receipt_data'] = {
                    'orders': orders_to_complete,
                    'barcode_id': receipt_barcode, 
                    'total_quantity': total_quantity,
                    'total_price': total_price,
                    'current_order_id': current_order_id
                }
                session.pop('current_order_id', None)
                
                flash('คำสั่งซื้อเสร็จสมบูรณ์แล้ว!', 'success')
                return redirect(url_for('receipt_display'))

            if 'products_id_input' in request.form and current_user_role in ['root_admin', 'administrator', 'moderator', 'member']:
                scanned_barcode_input = request.form.get('products_id_input').strip()
                pre_filled_products_id_input = scanned_barcode_input 

                if not scanned_barcode_input:
                    flash("กรุณากรอกรหัสบาร์โค้ด!", 'danger')
                    return redirect(url_for('cart'))
                
                if not scanned_barcode_input.isdigit() or len(scanned_barcode_input) != 13: 
                    flash("รหัสบาร์โค้ดไม่ถูกต้อง (ควรเป็นตัวเลข 13 หลัก)!", 'danger')
                    return redirect(url_for('cart'))

                product_info_query = "SELECT products_id, products_name, stock_quantity, price FROM tbl_products WHERE barcode_id = %s"
                product_info_params = [scanned_barcode_input]
                if current_user_store_id:
                    product_info_query += " AND (store_id = %s OR store_id IS NULL)" 
                    product_info_params.append(current_user_store_id)

                cursor.execute(product_info_query, tuple(product_info_params))
                product_info = cursor.fetchone()
                
                if not product_info:
                    flash("ไม่พบสินค้าด้วยรหัสบาร์โค้ดนี้ในร้านค้าของคุณ!", 'danger')
                    return redirect(url_for('cart'))

                order_id_to_use = session.get('current_order_id')

                email = request.form.get('email')
                if current_user_role == 'member':
                    email = session['email']
                elif not email: 
                    flash("กรุณาระบุอีเมลลูกค้า.", 'danger')
                    return redirect(url_for('cart'))

                quantity = 1 
                disquantity = 0 

                if quantity > product_info['stock_quantity']:
                    flash(f"สินค้า {product_info['products_name']} มีสต็อกไม่พอ. มีในสต็อก: {product_info['stock_quantity']} ชิ้น", 'danger')
                    return redirect(url_for('cart'))
                
                products_name_from_db = product_info['products_name']
                products_id_to_use = product_info['products_id']
                price_per_unit = product_info['price']
                
                item_store_id = product_info.get('store_id') if product_info.get('store_id') is not None else current_user_store_id
                if item_store_id is None: 
                    flash("ไม่สามารถระบุร้านค้าสำหรับรายการสั่งซื้อนี้ได้. โปรดติดต่อผู้ดูแลระบบ.", 'danger')
                    return redirect(url_for('cart'))


                cursor.execute("""
                    SELECT id, quantity FROM tbl_order 
                    WHERE products_id = %s AND order_id = %s AND email = %s AND store_id = %s
                """, (products_id_to_use, order_id_to_use, email, item_store_id))
                existing_order_item = cursor.fetchone()

                if existing_order_item:
                    new_qty = existing_order_item['quantity'] + quantity
                    if new_qty > product_info['stock_quantity']:
                        flash(f"ไม่สามารถเพิ่มได้ สินค้า {products_name_from_db} มีสต็อกไม่พอสำหรับยอดรวม. มีในสต็อก: {product_info['stock_quantity']} ชิ้น", 'danger')
                    else:
                        cursor.execute("UPDATE tbl_order SET quantity = %s WHERE id = %s", (new_qty, existing_order_item['id']))
                        cursor.execute("UPDATE tbl_products SET stock_quantity = stock_quantity - %s WHERE products_id = %s", (quantity, products_id_to_use))
                        conn.commit()
                        flash(f'เพิ่มจำนวนสินค้า {products_name_from_db} ในรายการสั่งซื้อ {order_id_to_use} สำเร็จ และอัปเดตสต็อกแล้ว!', 'success')
                else:
                    cursor.execute("""
                        INSERT INTO tbl_order (order_id, products_id, products_name, quantity, disquantity, email, barcode_id, store_id, price_per_unit)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (order_id_to_use, products_id_to_use, products_name_from_db, quantity, disquantity, email, scanned_barcode_input, item_store_id, price_per_unit))
                    cursor.execute("UPDATE tbl_products SET stock_quantity = stock_quantity - %s WHERE products_id = %s", (quantity, products_id_to_use))
                    conn.commit()
                    flash('เพิ่มคำสั่งซื้อสำเร็จและอัปเดตสต็อกสินค้าแล้ว!', 'success')
                
                selected_product_details_display = f"{product_info['products_name']} | สต็อก: {product_info['stock_quantity'] - quantity} | ราคา: {product_info['price']} บาท"

                return redirect(url_for('cart', pre_filled_products_id_input=pre_filled_products_id_input, 
                                         selected_product_details_display=selected_product_details_display))
            
            elif 'products_id_input' in request.form: 
                flash("คุณไม่มีสิทธิ์เพิ่มคำสั่งซื้อ", 'danger')
                return redirect(url_for('cart'))
        
        base_order_query = """
            SELECT o.*, p.price, p.products_name AS product_name_from_db, s.store_name
            FROM tbl_order o
            JOIN tbl_products p ON o.products_id = p.products_id
            LEFT JOIN tbl_users u ON o.email = u.email
            LEFT JOIN tbl_stores s ON o.store_id = s.store_id
            WHERE o.order_id = %s AND o.store_id = %s AND o.email = %s
        """
        query_params_orders = [current_order_id, current_user_store_id, session.get('email')]
        
        base_order_query += " ORDER BY o.id DESC" 
        cursor.execute(base_order_query, tuple(query_params_orders))
        orders_data = cursor.fetchall()
            
    except mysql.connector.Error as err:
        print(f"Error in cart: {err}") 
        flash(f"เกิดข้อผิดพลาดในฐานข้อมูล: {err}", 'danger')
        if conn: conn.rollback()
        orders_data = [] # Ensure empty on error
    except Exception as e:
        print(f"An unexpected error occurred in cart: {e}") 
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
        if conn: conn.rollback()
        orders_data = [] # Ensure empty on error
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
                           current_auto_order_id=current_order_id, 
                           request_form_data=request_form_data,
                           selected_product_details_display=selected_product_details_display,
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
        current_user_email = session.get('email')
        current_user_store_id = session.get('store_id')

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

        product_info_query = "SELECT stock_quantity, products_name, category_id FROM tbl_products WHERE products_id = %s"
        product_info_params = [products_id_from_form]
        if current_user_store_id:
            product_info_query += " AND (store_id = %s OR store_id IS NULL)" 
            product_info_params.append(current_user_store_id)
        
        cursor_edit.execute(product_info_query, tuple(product_info_params))
        product_info = cursor_edit.fetchone()

        if not product_info:
            flash(f"ไม่พบสินค้า ID {products_id_from_form} หรือสินค้าไม่ได้อยู่ในร้านค้าของคุณสำหรับแก้ไข.", 'danger')
            return redirect(url_for('cart'))

        current_stock_in_db = product_info['stock_quantity']
        category_id_for_bin_update = product_info['category_id']

        current_order_item_query = "SELECT quantity, disquantity, email, store_id FROM tbl_order WHERE id = %s AND order_id = %s AND products_id = %s"
        current_order_item_params = [item_id, order_id_from_form, products_id_from_form]
        
        if current_user_store_id:
            current_order_item_query += " AND store_id = %s"
            current_order_item_params.append(current_user_store_id)
        if session.get('role') == 'member':
            current_order_item_query += " AND email = %s"
            current_order_item_params.append(current_user_email)

        cursor_edit.execute(current_order_item_query, tuple(current_order_item_params))
        current_order_item_info = cursor_edit.fetchone()
        
        if not current_order_item_info:
            flash("ไม่พบรายการคำสั่งซื้อที่ต้องการแก้ไข หรือคุณไม่มีสิทธิ์แก้ไขรายการนี้!", 'danger')
            return redirect(url_for('cart'))

        current_order_qty = current_order_item_info['quantity']
        current_order_disqty = current_order_item_info['disquantity']
        order_item_store_id = current_order_item_info['store_id']

        if new_quantity <= 0:
            flash("จำนวนสินค้าต้องมากกว่า 0 หากต้องการลบ กรุณากดปุ่มลบ.", 'warning')
            return redirect(url_for('cart'))
        
        if new_disquantity < 0:
            flash("จำนวนทิ้งต้องไม่น้อยกว่า 0.", 'warning')
            return redirect(url_for('cart'))

        if new_disquantity > new_quantity:
            flash("จำนวนทิ้งต้องไม่สามารถมากกว่าจำนวนสินค้าทั้งหมดได้.", 'danger')
            return redirect(url_for('cart'))

        stock_to_restore = current_order_qty - new_quantity 
        
        if current_stock_in_db + stock_to_restore < 0:
            flash(f"ไม่สามารถแก้ไขได้: สินค้า {product_info['products_name']} มีสต็อกไม่พอ. สต็อกปัจจุบัน: {current_stock_in_db}, ต้องการปรับ: {stock_to_restore}.", 'danger')
            return redirect(url_for('cart'))

        cursor_edit.execute("""
            UPDATE tbl_order
            SET quantity = %s, disquantity = %s
            WHERE id = %s AND order_id = %s AND products_id = %s AND email = %s AND store_id = %s
        """, (new_quantity, new_disquantity, item_id, order_id_from_form, products_id_from_form, current_user_email, current_user_store_id)) 

        cursor_edit.execute("UPDATE tbl_products SET stock_quantity = stock_quantity + %s WHERE products_id = %s", (stock_to_restore, products_id_from_form))

        if new_disquantity > 0:
            cursor_edit.execute("UPDATE tbl_bin SET value = 1 WHERE category_id = %s AND store_id = %s", (category_id_for_bin_update, order_item_store_id))
        elif new_disquantity == 0 and current_order_disqty > 0: 
            cursor_edit.execute("""
                SELECT COUNT(*) FROM tbl_order o 
                JOIN tbl_products p ON o.products_id = p.products_id 
                WHERE p.category_id = %s AND o.disquantity > 0 AND o.store_id = %s AND o.id != %s
            """, (category_id_for_bin_update, order_item_store_id, item_id))
            remaining_disposed_in_category_in_store = cursor_edit.fetchone()[0]
            if remaining_disposed_in_category_in_store == 0:
                cursor_edit.execute("UPDATE tbl_bin SET value = 0 WHERE category_id = %s AND store_id = %s", (category_id_for_bin_update, order_item_store_id))


        conn_edit.commit()
        flash(f'แก้ไขรายการ ID {item_id} ในคำสั่งซื้อ {order_id_from_form} สำเร็จแล้ว!', 'success')

    except ValueError:
        flash("จำนวนและทิ้งต้องเป็นตัวเลขที่ถูกต้อง.", 'danger')
    except mysql.connector.Error as err:
        print(f"Error editing cart item: {err}") 
        flash(f"เกิดข้อผิดพลาดในการแก้ไขรายการ: {err}", 'danger')
        if conn_edit: conn_edit.rollback()
    except Exception as e:
        print(f"An unexpected error occurred: {e}") 
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
        current_user_email = session.get('email')
        current_user_store_id = session.get('store_id')

        conn_del = get_db_connection()
        if not conn_del:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return redirect(url_for('cart'))

        cursor_del = conn_del.cursor(dictionary=True)
        item_to_delete_query = """
            SELECT o.id, o.products_id, o.quantity, o.disquantity, o.order_id, p.category_id, o.store_id, o.email
            FROM tbl_order o
            JOIN tbl_products p ON o.products_id = p.products_id
            WHERE o.id = %s AND o.email = %s AND o.store_id = %s
        """
        cursor_del.execute(item_to_delete_query, (item_id, current_user_email, current_user_store_id))
        item_to_delete = cursor_del.fetchone()

        if not item_to_delete:
            flash('ไม่พบรายการคำสั่งซื้อ หรือคุณไม่มีสิทธิ์ลบรายการนี้!', 'danger')
            return redirect(url_for('cart'))

        product_id = item_to_delete['products_id']
        quantity_to_return = item_to_delete['quantity']
        category_id_of_deleted_item = item_to_delete['category_id']
        order_store_id = item_to_delete['store_id']

        cursor_del.execute("UPDATE tbl_products SET stock_quantity = stock_quantity + %s WHERE products_id = %s",
                           (quantity_to_return, product_id))
        
        cursor_del.execute("DELETE FROM tbl_order WHERE id = %s", (item_id,))
        
        cursor_del.execute("""
            SELECT COUNT(*) FROM tbl_order o 
            JOIN tbl_products p ON o.products_id = p.products_id 
            WHERE p.category_id = %s AND o.disquantity > 0 AND o.store_id = %s
        """, (category_id_of_deleted_item, order_store_id))
        remaining_disposed_in_category_in_store = cursor_del.fetchone()[0]
        if remaining_disposed_in_category_in_store == 0:
            cursor_del.execute("UPDATE tbl_bin SET value = 0 WHERE category_id = %s AND store_id = %s", (category_id_of_deleted_item, order_store_id))
            
        conn_del.commit()
        flash(f'ลบรายการ ID {item_id} ออกจากคำสั่งซื้อ {item_to_delete["order_id"]} สำเร็จแล้ว! สต็อกสินค้าได้รับการคืนแล้ว.', 'success')

    except mysql.connector.Error as err:
        print(f"Error deleting cart item: {err}") 
        flash(f"เกิดข้อผิดพลาดในการลบรายการ: {err}", 'danger')
        if conn_del: conn_del.rollback()
    except Exception as e:
        print(f"An unexpected error occurred: {e}") 
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

    current_user_role = session.get('role')
    current_user_store_id = session.get('store_id')

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
                SELECT o.id, o.quantity, o.disquantity, o.products_name, o.products_id, p.stock_quantity as stock, p.category_id, o.email, o.store_id
                FROM tbl_order o
                JOIN tbl_products p ON o.products_id = p.products_id
                WHERE o.barcode_id = %s AND o.products_id = %s AND o.store_id = %s
            """
            query_params_item = [barcode_id_to_search, products_id_to_disquantity, current_user_store_id]

            if current_user_role == 'member':
                base_query_item += " AND o.email = %s"
                query_params_item.append(session['email'])
            
            cursor.execute(base_query_item, tuple(query_params_item))
            order_item_to_update = cursor.fetchone()

            if order_item_to_update:
                current_quantity = order_item_to_update['quantity']
                current_disquantity = order_item_to_update['disquantity']
                category_id_for_bin = order_item_to_update.get('category_id')
                item_store_id = order_item_to_update['store_id']

                if category_id_for_bin is None:
                    flash(f"ไม่พบ category_id สำหรับสินค้า '{order_item_to_update['products_name']}'. ไม่สามารถอัปเดต bin ได้.", 'danger')
                    return redirect(url_for('bin', barcode_id_filter=barcode_id_filter))

                proposed_disquantity = current_disquantity + 1

                if proposed_disquantity <= current_quantity:
                    cursor.execute("UPDATE tbl_order SET disquantity = %s WHERE id = %s",
                                   (proposed_disquantity, order_item_to_update['id']))

                    cursor.execute("UPDATE tbl_bin SET value = 1 WHERE category_id = %s AND store_id = %s", (category_id_for_bin, item_store_id))

                    conn.commit()
                    flash(f"เพิ่มจำนวนทิ้งสินค้า '{order_item_to_update['products_name']}' (รหัสสินค้า: {products_id_to_disquantity}) สำเร็จ. สถานะ bin (category_id: {category_id_for_bin}, store_id: {item_store_id}) ได้รับการอัปเดตแล้ว.", 'success')
                else:
                    flash(f"ไม่สามารถเพิ่มจำนวนทิ้งได้เกินจำนวนสินค้าที่สั่งซื้อ ({current_quantity} ชิ้น) สำหรับสินค้า '{order_item_to_update['products_name']}'", 'danger')
            else:
                flash("ไม่พบรายการสินค้าที่ตรงกันสำหรับรหัสบาร์โค้ดและรหัสสินค้าที่ระบุในร้านค้าของคุณ.", 'danger')
            return redirect(url_for('bin', barcode_id_filter=barcode_id_filter))

        base_query = """
            SELECT o.*, p.price, p.products_name, p.category_id, o.email AS user_email_from_db, o.store_id, s.store_name
            FROM tbl_order o
            JOIN tbl_products p ON o.products_id = p.products_id
            LEFT JOIN tbl_users u ON o.email = u.email
            LEFT JOIN tbl_stores s ON o.store_id = s.store_id
            WHERE o.barcode_id = %s AND o.store_id = %s
        """
        query_params = [barcode_id_filter, current_user_store_id]

        if current_user_role == 'member':
            base_query += " AND o.email = %s"
            query_params.append(session['email'])
        
        base_query += " ORDER BY o.id DESC"
        cursor.execute(base_query, tuple(query_params))
        orders_data = cursor.fetchall()

    except mysql.connector.Error as err:
        print(f"Error in bin: {err}") 
        flash(f"เกิดข้อผิดพลาดในการดึงข้อมูลคำสั่งซื้อ: {err}", 'danger')
        if conn: conn.rollback()
        orders_data = [] # Ensure empty on error
    except Exception as e:
        print(f"An unexpected error occurred in bin: {e}") 
        flash(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", 'danger')
        if conn: conn.rollback()
        orders_data = [] # Ensure empty on error
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
        current_user_email = session.get('email')
        current_user_store_id = session.get('store_id')

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

        old_order_item_query = "SELECT quantity, disquantity, email, store_id FROM tbl_order WHERE id = %s AND order_id = %s AND products_id = %s AND store_id = %s"
        old_order_item_params = [item_id, order_id_from_form, products_id_from_form, current_user_store_id]
        if session.get('role') == 'member':
            old_order_item_query += " AND email = %s"
            old_order_item_params.append(current_user_email)

        cursor_edit.execute(old_order_item_query, tuple(old_order_item_params))
        old_order_item = cursor_edit.fetchone()

        if not old_order_item:
            flash(f"ไม่พบรายการ ID {item_id} สำหรับแก้ไข หรือคุณไม่มีสิทธิ์แก้ไขรายการนี้.", 'danger')
            return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))

        old_quantity = old_order_item['quantity']
        old_disquantity = old_order_item['disquantity']
        order_item_store_id = old_order_item['store_id']

        product_info_query = "SELECT stock_quantity, products_name, category_id FROM tbl_products WHERE products_id = %s AND (store_id = %s OR store_id IS NULL)"
        cursor_edit.execute(product_info_query, (products_id_from_form, current_user_store_id))
        product_info = cursor_edit.fetchone()

        if not product_info:
            flash(f"ไม่พบข้อมูลสินค้า ID {products_id_from_form} ในร้านค้าของคุณ.", 'danger')
            return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))

        current_stock = product_info['stock_quantity']
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

        stock_change = (old_quantity - new_quantity) + (new_disquantity - old_disquantity)
        
        if current_stock + stock_change < 0:
            flash(f"ไม่สามารถแก้ไขได้: สินค้า '{product_info['products_name']}' มีสต็อกไม่พอสำหรับการเปลี่ยนแปลงนี้ (สต็อกปัจจุบัน: {current_stock}, ต้องการปรับ: {stock_change}).", 'danger')
            return redirect(url_for('bin', barcode_id_filter=barcode_id_for_redirect))

        cursor_edit.execute("""
            UPDATE tbl_order
            SET quantity = %s, disquantity = %s
            WHERE id = %s AND order_id = %s AND products_id = %s AND email = %s AND store_id = %s
        """, (new_quantity, new_disquantity, item_id, order_id_from_form, products_id_from_form, current_user_email, current_user_store_id))

        cursor_edit.execute("UPDATE tbl_products SET stock_quantity = stock_quantity + %s WHERE products_id = %s",
                            (stock_change, products_id_from_form))

        if new_disquantity > 0:
            cursor_edit.execute("UPDATE tbl_bin SET value = 1 WHERE category_id = %s AND store_id = %s", (category_id_for_bin_update, order_item_store_id))
        elif new_disquantity == 0 and current_order_disqty > 0: 
            cursor_edit.execute("""
                SELECT COUNT(*) FROM tbl_order o 
                JOIN tbl_products p ON o.products_id = p.products_id 
                WHERE p.category_id = %s AND o.disquantity > 0 AND o.store_id = %s AND o.id != %s
            """, (category_id_for_bin_update, order_item_store_id, item_id))
            remaining_disposed_in_category_in_store = cursor_edit.fetchone()[0]
            if remaining_disposed_in_category_in_store == 0:
                cursor_edit.execute("UPDATE tbl_bin SET value = 0 WHERE category_id = %s AND store_id = %s", (category_id_for_bin_update, order_item_store_id))

        conn_edit.commit()
        flash(f'แก้ไขรายการ ID {item_id} (สินค้า: {product_info["products_name"]}) ในคำสั่งซื้อ {order_id_from_form} สำเร็จแล้ว!', 'success')

    except ValueError:
        flash("จำนวนและทิ้งต้องเป็นตัวเลขที่ถูกต้อง.", 'danger')
    except mysql.connector.Error as err:
        print(f"Error editing bin item: {err}") 
        flash(f"เกิดข้อผิดพลาดในการแก้ไขรายการ: {err}", 'danger')
        if conn_edit: conn_edit.rollback()
    except Exception as e:
        print(f"An unexpected error occurred: {e}") 
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
        current_user_email = session.get('email')
        current_user_store_id = session.get('store_id')

        conn_del = get_db_connection()
        if not conn_del:
            flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล.", 'danger')
            return redirect(url_for('bin'))

        cursor_del = conn_del.cursor(dictionary=True)
        item_to_delete_query = """
            SELECT o.id, o.products_id, o.quantity, o.disquantity, o.order_id, o.barcode_id, o.email, p.category_id, o.store_id
            FROM tbl_order o
            JOIN tbl_products p ON o.products_id = p.products_id
            WHERE o.id = %s AND o.email = %s AND o.store_id = %s
        """
        cursor_del.execute(item_to_delete_query, (item_id, current_user_email, current_user_store_id))
        item_to_delete = cursor_del.fetchone()

        if not item_to_delete:
            flash("ไม่พบรายการที่จะลบ.", 'danger')
            return redirect(url_for('bin'))

        item_barcode_id = item_to_delete['barcode_id']
        category_id_of_deleted_item = item_to_delete['category_id']
        order_store_id = item_to_delete['store_id']

        cursor_del.execute("UPDATE tbl_products SET stock_quantity = stock_quantity + %s WHERE products_id = %s",
                            (item_to_delete['quantity'], item_to_delete['products_id']))

        cursor_del.execute("DELETE FROM tbl_order WHERE id = %s", (item_id,))
        
        cursor_del.execute("""
            SELECT COUNT(*) FROM tbl_order o 
            JOIN tbl_products p ON o.products_id = p.products_id 
            WHERE p.category_id = %s AND o.disquantity > 0 AND o.store_id = %s
        """, (category_id_of_deleted_item, order_store_id))
        remaining_disposed_in_category_in_store = cursor_del.fetchone()[0]
        if remaining_disposed_in_category_in_store == 0:
            cursor_del.execute("UPDATE tbl_bin SET value = 0 WHERE category_id = %s AND store_id = %s", (category_id_of_deleted_item, order_store_id))
            
        conn_del.commit()
        flash(f'ลบรายการ ID {item_id} ออกจากคำสั่งซื้อ {item_to_delete["order_id"]} สำเร็จแล้ว! สต็อกสินค้าได้รับการคืนแล้ว.', 'success')

    except mysql.connector.Error as err:
        print(f"Error deleting bin item: {err}") 
        flash(f"เกิดข้อผิดพลาดในการลบรายการ: {err}", 'danger')
        if conn_del: conn_del.rollback()
    except Exception as e:
        print(f"An unexpected error occurred: {e}") 
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
