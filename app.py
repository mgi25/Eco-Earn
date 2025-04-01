import os
import time
import json
from functools import wraps
from flask import Flask, render_template, request, url_for, redirect, flash, session
from pymongo import MongoClient
from config import DB_URL
import bcrypt
from bson import ObjectId
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # Replace with your secret key
client = MongoClient(DB_URL)
db = client['ecoearn']
app.config['db'] = db

# File upload configuration
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024  # 64 MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    flash("File size exceeds limit. Please upload smaller files or split your uploads into multiple sessions.")
    return redirect(request.url)

# -----------------------
# MAIN APPLICATION ROUTES
# -----------------------

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        terms = request.form.get('terms')
        if not terms:
            flash("You must agree to the terms and policy!")
            return redirect(url_for('signup'))
        existing_user = db.users.find_one({"email": email})
        if existing_user:
            flash("Email already registered. Please log in.")
            return redirect(url_for('login'))
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        db.users.insert_one({
            "name": name,
            "email": email,
            "password": hashed,
            "rewards": 0,
            "items_recycled": 0,
            "admin": False
        })
        flash("Signup successful! Please log in.")
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email').lower()
        password = request.form.get('password')
        # Hardcoded admin credentials for testing:
        if email == 'admin@example.com' and password == 'admin123':
            session['user_id'] = 'admin'
            session['is_admin'] = True
            flash("Admin login successful!")
            return redirect(url_for('admin_dashboard'))
        user = db.users.find_one({"email": email})
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password']):
            session['user_id'] = str(user['_id'])
            session['is_admin'] = user.get('admin', False)
            flash("Login successful!")
            return redirect(url_for('home'))
        else:
            flash("Invalid email or password!")
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/home')
def home():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    if session['user_id'] == 'admin':
        user = {"name": "Admin"}
    else:
        user = db.users.find_one({"_id": ObjectId(session['user_id'])})
    announcements = list(db.announcements.find())
    for ann in announcements:
        ann['_id'] = str(ann['_id'])
    return render_template('home.html', user=user, announcements=announcements)

@app.route('/scan_item', methods=['GET', 'POST'])
def scan_item():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    if request.method == 'POST':
        if 'item_image' in request.files and request.files['item_image'].filename != '':
            file = request.files['item_image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(save_path)
                flash("File uploaded successfully! (Simulating scan...)")
                return redirect(url_for('scan_item'))
            else:
                flash("Invalid file type! Please upload an image file.")
                return redirect(request.url)
        photos_json = request.form.get('photosBase64')
        if photos_json:
            try:
                photos_list = json.loads(photos_json)
                count = 0
                for base64_str in photos_list:
                    header, encoded = base64_str.split(',', 1)
                    img_data = base64.b64decode(encoded)
                    filename = f"captured_{int(time.time())}_{count}.png"
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    with open(save_path, 'wb') as f:
                        f.write(img_data)
                    count += 1
                flash(f"{count} captured photo(s) uploaded successfully! (Simulating scan...)")
                return redirect(request.url)
            except Exception as e:
                flash(f"Error saving captured photos: {e}")
                return redirect(request.url)
        flash("Please select a file or capture some photos.")
        return redirect(request.url)
    return render_template('scan_item.html')

# -----------------------
# RECYCLING CENTERS
# -----------------------
@app.route('/recycling_centers')
def recycling_centers():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    if lat and lon:
        try:
            lat_val = float(lat)
            lon_val = float(lon)
            centers_cursor = db.recyclingCenters.find({
                "location": {
                    "$exists": True,
                    "$ne": None,
                    "$near": {
                        "$geometry": {
                            "type": "Point",
                            "coordinates": [lon_val, lat_val]
                        },
                        "$maxDistance": 50000  # 50 km
                    }
                }
            })
            centers = []
            for c in centers_cursor:
                c['_id'] = str(c['_id'])
                centers.append(c)
            user_location = {"lat": lat_val, "lon": lon_val}
            return render_template('recycling_centers.html', centers=centers, user_location=user_location)
        except ValueError:
            flash("Invalid location data.")
            return redirect(url_for('recycling_centers'))
    centers = list(db.recyclingCenters.find())
    for center in centers:
        center['_id'] = str(center['_id'])
    return render_template('recycling_centers.html', centers=centers, user_location=None)

@app.route('/recycling_centers/<center_id>/map')
def center_map(center_id):
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    center = db.recyclingCenters.find_one({"_id": ObjectId(center_id)})
    if not center:
        flash("Recycling center not found!")
        return redirect(url_for('recycling_centers'))
    center['_id'] = str(center['_id'])
    return render_template('center_map.html', center=center)

@app.route('/transactions')
def transactions():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    transactions = list(db.transactions.find())
    for trans in transactions:
        trans['_id'] = str(trans['_id'])
    return render_template('transactions.html', transactions=transactions)

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully!")
    return redirect(url_for('login'))

# -----------------------
# ADMIN ROUTES (Protected)
# -----------------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            flash("Admin access required!")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    users = list(db.users.find())
    centers = list(db.recyclingCenters.find())
    items = list(db.items.find()) if 'items' in db.list_collection_names() else []
    transactions = list(db.transactions.find()) if 'transactions' in db.list_collection_names() else []
    stats = {
        "total_users": len(users),
        "total_centers": len(centers),
        "total_items": len(items),
        "total_transactions": len(transactions)
    }
    return render_template('admin_dashboard.html', stats=stats)

@app.route('/admin/users')
@admin_required
def admin_users():
    users = list(db.users.find())
    for user in users:
        user['_id'] = str(user['_id'])
    return render_template('admin_users.html', users=users)

@app.route('/admin/centers')
@admin_required
def admin_centers():
    centers = list(db.recyclingCenters.find())
    for center in centers:
        center['_id'] = str(center['_id'])
    return render_template('admin_centers.html', centers=centers)

@app.route('/admin/items')
@admin_required
def admin_items():
    items = list(db.items.find()) if 'items' in db.list_collection_names() else []
    for item in items:
        item['_id'] = str(item['_id'])
    return render_template('admin_items.html', items=items)

@app.route('/admin/transactions')
@admin_required
def admin_transactions():
    transactions = list(db.transactions.find()) if 'transactions' in db.list_collection_names() else []
    for trans in transactions:
        trans['_id'] = str(trans['_id'])
    return render_template('admin_transactions.html', transactions=transactions)

# -----------------------
# ADMIN CRUD FOR RECYCLING CENTERS
# -----------------------
@app.route('/admin/centers/add', methods=['GET', 'POST'])
@admin_required
def admin_add_center():
    if request.method == 'POST':
        name = request.form.get('name')
        address = request.form.get('address')
        accepted_items = request.form.get('accepted_items')
        accepted_items_list = [item.strip() for item in accepted_items.split(',')] if accepted_items else []
        lat = request.form.get('latitude')
        lon = request.form.get('longitude')
        
        # Handle center image upload
        image_file = request.files.get('center_image')
        image_url = None
        if image_file and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(save_path)
            image_url = "uploads/" + filename
        
        center = {
            "name": name,
            "address": address,
            "acceptedItems": accepted_items_list,
            "location": {"type": "Point", "coordinates": [float(lon), float(lat)]} if lat and lon else None,
            "image": image_url
        }
        db.recyclingCenters.insert_one(center)
        flash("Recycling center added successfully!")
        return redirect(url_for('admin_centers'))
    return render_template('admin_center_form.html', action="Add", center={})

@app.route('/admin/centers/edit/<center_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_center(center_id):
    center = db.recyclingCenters.find_one({"_id": ObjectId(center_id)})
    if not center:
        flash("Center not found!")
        return redirect(url_for('admin_centers'))
    if request.method == 'POST':
        name = request.form.get('name')
        address = request.form.get('address')
        accepted_items = request.form.get('accepted_items')
        accepted_items_list = [item.strip() for item in accepted_items.split(',')] if accepted_items else []
        lat = request.form.get('latitude')
        lon = request.form.get('longitude')
        
        # Check if a new image was uploaded
        image_file = request.files.get('center_image')
        image_url = center.get("image")
        if image_file and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(save_path)
            image_url = "uploads/" + filename
        
        update_data = {
            "name": name,
            "address": address,
            "acceptedItems": accepted_items_list,
            "location": {"type": "Point", "coordinates": [float(lon), float(lat)]} if lat and lon else center.get("location"),
            "image": image_url
        }
        db.recyclingCenters.update_one({"_id": ObjectId(center_id)}, {"$set": update_data})
        flash("Recycling center updated successfully!")
        return redirect(url_for('admin_centers'))
    
    center['accepted_items_str'] = ", ".join(center.get("acceptedItems", []))
    if center.get("location"):
        center['latitude'] = center['location']['coordinates'][1]
        center['longitude'] = center['location']['coordinates'][0]
    else:
        center['latitude'] = ""
        center['longitude'] = ""
    center['_id'] = str(center['_id'])
    return render_template('admin_center_form.html', action="Edit", center=center)

@app.route('/admin/centers/delete/<center_id>', methods=['POST'])
@admin_required
def admin_delete_center(center_id):
    result = db.recyclingCenters.delete_one({"_id": ObjectId(center_id)})
    if result.deleted_count:
        flash("Recycling center deleted successfully!")
    else:
        flash("Recycling center not found!")
    return redirect(url_for('admin_centers'))

# -----------------------
# ADMIN CRUD FOR ANNOUNCEMENTS
# -----------------------
@app.route('/admin/announcements')
@admin_required
def admin_announcements():
    announcements = list(db.announcements.find())
    for ann in announcements:
        ann['_id'] = str(ann['_id'])
    return render_template('admin_announcements.html', announcements=announcements)

@app.route('/admin/announcements/add', methods=['GET', 'POST'])
@admin_required
def admin_add_announcement():
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        image_file = request.files.get('announcement_image')
        image_url = None
        if image_file and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(save_path)
            image_url = "uploads/" + filename
        announcement = {
            "title": title,
            "content": content,
            "image": image_url,
            "date": time.strftime("%Y-%m-%d")
        }
        db.announcements.insert_one(announcement)
        flash("Announcement added successfully!")
        return redirect(url_for('admin_announcements'))
    return render_template('admin_announcement_form.html', action="Add", announcement={})

@app.route('/admin/announcements/edit/<announcement_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_announcement(announcement_id):
    announcement = db.announcements.find_one({"_id": ObjectId(announcement_id)})
    if not announcement:
        flash("Announcement not found!")
        return redirect(url_for('admin_announcements'))
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        image_file = request.files.get('announcement_image')
        image_url = announcement.get("image")
        if image_file and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(save_path)
            image_url = "uploads/" + filename
        update_data = {
            "title": title,
            "content": content,
            "image": image_url
        }
        db.announcements.update_one({"_id": ObjectId(announcement_id)}, {"$set": update_data})
        flash("Announcement updated successfully!")
        return redirect(url_for('admin_announcements'))
    announcement['_id'] = str(announcement['_id'])
    return render_template('admin_announcement_form.html', action="Edit", announcement=announcement)

@app.route('/admin/announcements/delete/<announcement_id>', methods=['POST'])
@admin_required
def admin_delete_announcement(announcement_id):
    result = db.announcements.delete_one({"_id": ObjectId(announcement_id)})
    if result.deleted_count:
        flash("Announcement deleted successfully!")
    else:
        flash("Announcement not found!")
    return redirect(url_for('admin_announcements'))

if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    app.run(debug=True)
