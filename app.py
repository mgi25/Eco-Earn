import os
import base64
import time
import json
from flask import Flask, render_template, request, url_for, redirect, flash, session
from pymongo import MongoClient
from config import DB_URL
import bcrypt
from bson import ObjectId
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

client = MongoClient(DB_URL)
db = client['ecoearn']  # using the "ecoearn" database

app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # Replace with your secret key

# Increase maximum allowed payload to 64 MB
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024  # 64 MB

UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    flash("File size exceeds limit. Please upload smaller files or split your uploads into multiple sessions.")
    return redirect(request.url)

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
            "items_recycled": 0
        })
        flash("Signup successful! Please log in.")
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = db.users.find_one({"email": email})
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password']):
            session['user_id'] = str(user['_id'])
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
    user_id = session['user_id']
    user = db.users.find_one({"_id": ObjectId(user_id)})
    return render_template('home.html', user=user)

@app.route('/scan_item', methods=['GET', 'POST'])
def scan_item():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        # Option 1: File upload
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
        
        # Option 2: Captured photos (JSON array of base64 images)
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
                return redirect(url_for('scan_item'))
            except Exception as e:
                flash(f"Error saving captured photos: {e}")
                return redirect(request.url)
        
        flash("Please select a file or capture some photos.")
        return redirect(request.url)
    
    return render_template('scan_item.html')

# UPDATED Recycling Centers Route:
@app.route('/recycling_centers')
def recycling_centers():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    # Query all recycling centers from the database
    centers = list(db.recyclingCenters.find())
    return render_template('recycling_centers.html', centers=centers)

@app.route('/transactions')
def transactions():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    return render_template('transactions.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully!")
    return redirect(url_for('login'))

if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    app.run(debug=True)
