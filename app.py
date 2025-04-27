
import os
import time
import json
import base64  # <-- IMPORTANT: import base64 to fix the undefined error
from functools import wraps
from flask import Flask, render_template, request, url_for, redirect, flash, session,jsonify    
from pymongo import MongoClient
from config import DB_URL
import bcrypt
from bson import ObjectId
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename
import requests
import uuid
import re
from markupsafe import Markup
from datetime import datetime
import calendar

app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # Replace with your secret key

# Connect to MongoDB
client = MongoClient(DB_URL)
db = client['ecoearn']
app.config['db'] = db

# Ensure 2dsphere index for recyclingCenters
if "location_2dsphere" not in db.recyclingCenters.index_information():
    db.recyclingCenters.create_index({"location": "2dsphere"})

# File upload configuration
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 128 * 1024 * 1024  # 128 MB


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
            "admin": False,
            "createdAt": datetime.now().strftime("%Y-%m-%d")
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
        user = {"name": "Admin", "rewards": 0, "items_recycled": 0}
    else:
        user = db.users.find_one({"_id": ObjectId(session['user_id'])})

        # ✅ Count items where user’s item was approved
        recycled_count = db.connected_items.count_documents({
            "userId": session['user_id'],
            "status": "Approved"
        })
        user['items_recycled'] = recycled_count

    announcements = list(db.announcements.find())
    for ann in announcements:
        ann['_id'] = str(ann['_id'])

    return render_template('home.html', user=user, announcements=announcements)


# AI prediction
RECYCLABLE_KEYWORDS = [
    "plastic", "metal", "steel", "stainless", "aluminum", "can", "bottle",
    "glass", "tin", "container", "jar", "foil", "cup", "recyclable",
    "carton", "paper", "cardboard"
]

def is_recyclable_item(text):
    if not text:
        return False
    text = text.lower()
    return any(keyword in text for keyword in RECYCLABLE_KEYWORDS)

def reason_suggests_non_recyclable(reason):
    if not reason:
        return False
    reason = reason.lower()
    strong_blocks = [
        "not recyclable", "cannot be recycled", "non-recyclable", "not accepted in any form"
    ]
    return any(phrase in reason for phrase in strong_blocks)

def prediction_has_conflict(prediction):
    return (
        "type: unknown" in prediction.lower() and
        ("recyclable" in prediction.lower() or "₹" in prediction.lower())
    )

def extract_fields(prediction):
    type_match = re.search(r'type:\s*(.+)', prediction, re.IGNORECASE)
    value_match = re.search(r'estimated value:\s*[₹]?(.*)', prediction, re.IGNORECASE)
    reason_match = re.search(r'reason:\s*(.+)', prediction, re.IGNORECASE)

    material_type = type_match.group(1).strip() if type_match else "Unknown"
    estimated_value = value_match.group(1).strip() if value_match else "0"
    reason = reason_match.group(1).strip() if reason_match else ""

    if "stainless steel" in reason.lower() and "plastic" in material_type.lower():
        material_type = "Stainless Steel"
    elif "aluminum" in material_type.lower() and "stainless steel" in reason.lower():
        material_type = "Stainless Steel"

    return {
        "material_type": material_type,
        "estimated_value": estimated_value,
        "reason": reason
    }

@app.route('/scan_item', methods=['GET', 'POST'])
def scan_item():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))

    if request.method == 'POST':
        uploaded_file = request.files.get('image')
        if not uploaded_file:
            flash("No file uploaded.", "error")
            return redirect(url_for('scan_item'))

        filename = secure_filename(uploaded_file.filename)
        unique_name = f"captured_{uuid.uuid4().hex[:10]}_{filename}"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
        uploaded_file.save(save_path)

        try:
            with open(save_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llava",
                    "prompt": (
                        "You are an AI that analyzes images to determine whether an item is recyclable. "
                        "Be very specific about material type. For example, say 'Stainless Steel' not just 'Metal'. "
                        "Respond in a structured format:\n"
                        "Type: [material]\nEstimated Value: ₹[amount]\nReason: [why or why not it's recyclable]. "
                        "Always be accurate. If it looks like a vehicle or unrelated object, respond with 'Type: Unknown' "
                        "and mark as not recyclable."
                    ),
                    "images": [image_data],
                    "stream": True
                },
                stream=True
            )

            prediction = ""
            for line in response.iter_lines():
                if line:
                    json_data = json.loads(line.decode('utf-8'))
                    prediction += json_data.get("response", "")

        except Exception as e:
            flash(f"AI prediction failed: {e}", "error")
            return redirect(url_for('scan_item'))

        # Extract fields from prediction
        fields = extract_fields(prediction)
        print("🔍 Extracted:", fields)  # Debug

        recyclable = (
            is_recyclable_item(fields['material_type']) and
            fields['material_type'].lower() != "unknown" and
            not reason_suggests_non_recyclable(fields['reason']) and
            not prediction_has_conflict(prediction)
        )

        # Store in session for display
        session['last_prediction'] = prediction
        session['recyclable'] = recyclable
        session['material_type'] = fields['material_type']
        session['estimated_value'] = fields['estimated_value']
        session['reason'] = fields['reason']

        if not recyclable:
            os.remove(save_path)
            flash("⚠️ This doesn't appear to be a recyclable item. Try uploading a clear image of plastic, bottle, can, or similar.", "error")
        else:
            # Save to database
            item_data = {
                "userId": session['user_id'],
                "image_path": "uploads/" + unique_name,
                "material_type": fields['material_type'],
                "estimated_value": fields['estimated_value'],
                "reason": fields['reason'],
                "status": "Pending Connection",
                "timestamp": time.strftime("%Y-%m-%d")
            }
            inserted = db.items.insert_one(item_data)
            item_id = str(inserted.inserted_id)

            session['connect_item_id'] = item_id
            flash("✅ Item is recyclable!")



        return redirect(url_for('scan_item'))

    return render_template('scan_item.html')



# -----------------------
# RECYCLING CENTERS ROUTE
# -----------------------
@app.route('/recycling_centers')
def recycling_centers():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))

    lat_str = request.args.get('lat')
    lon_str = request.args.get('lon')
    centers = []
    user_location = None

    if lat_str and lon_str:
        try:
            lat_val = float(lat_str)
            lon_val = float(lon_str)
            if -90 <= lat_val <= 90 and -180 <= lon_val <= 180:
                pipeline = [
                    {
                        "$geoNear": {
                            "near": {"type": "Point", "coordinates": [lon_val, lat_val]},
                            "distanceField": "distance",
                            "maxDistance": 50000,
                            "spherical": True
                        }
                    }
                ]
                centers = list(db.recyclingCenters.aggregate(pipeline))
                for c in centers:
                    c['_id'] = str(c['_id'])
                user_location = {"lat": lat_val, "lon": lon_val}
            else:
                flash("Location out of range. Showing all centers unsorted.")
        except ValueError:
            flash("Invalid location data. Showing all centers unsorted.")
        except Exception as e:
            flash(f"Error during geo query: {e}")

    if not centers:
        centers = list(db.recyclingCenters.find())
        for center in centers:
            center['_id'] = str(center['_id'])
        user_location = None

    return render_template('recycling_centers.html', centers=centers, user_location=user_location)

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
# MY ITEMS, TRANSACTION HISTORY, REDEEM REWARDS ROUTES
# -----------------------
@app.route('/my_items')
def my_items():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))

    user_id = session['user_id']
    user_items = db.items.find({"userId": user_id})
    items_list = []

    for item in user_items:
        items_list.append({
            "_id": str(item["_id"]),
            "material_type": item.get("material_type", "Unknown"),
            "status": item.get("status", "Pending"),
            "estimated_value": item.get("estimated_value", "N/A"),
            "timestamp": item.get("timestamp", "N/A"),
            "image_path": item.get("image_path", None)
        })

    return render_template("my_items.html", items=items_list)


@app.route('/transaction_history')
def transaction_history():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))

    user_id = session['user_id']
    # 👉 Only find withdrawal transactions now
    user_transactions = db.transactions.find({
        "userId": user_id,
        "type": "withdrawal"
    })

    transactions_list = []
    for tx in user_transactions:
        tx['_id'] = str(tx['_id'])
        transactions_list.append(tx)

    return render_template('transaction_history.html', transactions=transactions_list)

@app.route('/redeem_rewards', methods=['GET', 'POST'])
def redeem_rewards():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))

    user = db.users.find_one({"_id": ObjectId(session['user_id'])})

    if request.method == 'POST':
        redeem_amount = request.form.get('redeem_amount')
        if redeem_amount:
            try:
                redeem_value = float(redeem_amount)
                current_rewards = user.get('rewards', 0)

                if redeem_value > current_rewards:
                    flash("You do not have enough rewards to redeem that amount.")
                else:
                    # Store the redeem_value in session for the next step
                    session['redeem_value'] = redeem_value
                    # Go to redeem_details route
                    return redirect(url_for('redeem_details'))

            except ValueError:
                flash("Please enter a valid number.")

        return redirect(url_for('redeem_rewards'))

    # GET request: just show the form
    return render_template('redeem_rewards.html', user=user)

@app.route('/redeem_details', methods=['GET', 'POST'])
def redeem_details():
    """Collect bank/payment info, finalize redemption."""
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))

    # Make sure we have a redeem_value stored
    redeem_value = session.get('redeem_value')
    if not redeem_value:
        flash("Please enter an amount to redeem first.")
        return redirect(url_for('redeem_rewards'))

    user = db.users.find_one({"_id": ObjectId(session['user_id'])})
    current_rewards = user.get('rewards', 0)

    if request.method == 'POST':
        # Get bank/payment fields
        bank_name = request.form.get('bank_name')
        account_number = request.form.get('account_number')
        ifsc_code = request.form.get('ifsc_code')

        # Validate the fields (simple example)
        if not (bank_name and account_number and ifsc_code):
            flash("Please fill all payment details.")
            return redirect(url_for('redeem_details'))

        # Double-check user still has enough points
        if redeem_value > current_rewards:
            flash("You no longer have enough rewards to redeem that amount.")
            return redirect(url_for('redeem_rewards'))

        # ✅ Deduct points from user
        db.users.update_one(
            {"_id": ObjectId(session['user_id'])},
            {"$inc": {"rewards": -redeem_value}}
        )

        # ✅ Insert proper withdrawal transaction
        add_transaction(session['user_id'], "withdrawal", redeem_value)

        # Clear the session redeem_value
        session.pop('redeem_value', None)

        # Redirect to success page with the redeemed amount
        return redirect(url_for('redeem_success', amount=redeem_value))

    # GET request: show the payment form
    return render_template('redeem_details.html', redeem_value=redeem_value)


@app.route('/redeem_success')
def redeem_success():
    """Display a confirmation page after redeeming points."""
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))

    # Retrieve the redeemed amount from query string
    redeem_amount = request.args.get('amount', 0)
    return render_template('redeem_success.html', redeem_amount=redeem_amount)


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

    # ✅ Fix: count both missing "verified" and explicitly False
    pending_centers = db.center_logins.count_documents({
        "$or": [
            {"verified": False},
            {"verified": {"$exists": False}}
        ],
        "status": {"$ne": "Rejected"}
    })

    stats = {
        "total_users": len(users),
        "total_centers": len(centers),
        "total_items": len(items),
        "total_transactions": len(transactions),
        "pending_centers": pending_centers,
        "pending_updates": db.center_update_requests.count_documents({"status": "Pending"})
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
            "image": image_url,
            "createdAt": datetime.now().strftime("%Y-%m-%d")
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


@app.route('/profile')
def profile():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    
    user = db.users.find_one({"_id": ObjectId(session['user_id'])})
    if not user:
        flash("User not found. Please log in again.")
        return redirect(url_for('login'))
    
    # (Optional) Count items to show real stats:
    # Only count items marked as recycled
    recycled_count = db.items.count_documents({
    "userId": session['user_id'],
    "status": "Recycled"
    })
    user['items_recycled'] = recycled_count


    return render_template('profile.html', user=user)


@app.route('/profile/edit', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    
    user = db.users.find_one({"_id": ObjectId(session['user_id'])})
    if not user:
        flash("User not found. Please log in again.")
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        address = request.form.get('address')

        update_data = {
            "name": name,
            "email": email,
            "phone": phone,
            "address": address
        }

        # Check if a new profile image was uploaded
        if 'profile_image' in request.files and request.files['profile_image'].filename != '':
            file = request.files['profile_image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(save_path)
                # e.g. "uploads/filename.jpg"
                update_data["profilePicture"] = f"uploads/{filename}"
            else:
                flash("Invalid file type for profile picture. Please upload a valid image.")
                return redirect(url_for('edit_profile'))
        
        # Update user document in MongoDB
        db.users.update_one({"_id": ObjectId(session['user_id'])}, {"$set": update_data})
        flash("Profile updated successfully!")
        return redirect(url_for('profile'))
    
    # GET request: just show the edit form
    return render_template('profile_edit.html', user=user)


@app.route('/home_chat_api', methods=['POST'])
def home_chat_api():
    data = request.get_json()
    user_msg = data.get("message", "")

    prompt = f"""
You are EcoBot, the official assistant of EcoEarn.

Your mission is to help users understand what EcoEarn is, how it works, what the goals are, and how to use the features like scanning, recycling centers, rewards, transactions, and profiles.

EcoEarn is a platform that allows users to upload or scan recyclable items, earn points or cash based on item type, and view nearby recycling centers.

Now the user asks: "{user_msg}"

Provide a helpful, polite, and informative answer in plain English.
"""

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3",  # or mixtral if supported
                "prompt": prompt,
                "stream": False
            }
        )
        result = response.json()
        return {"reply": result.get("response", "Sorry, I couldn't answer that right now.")}
    except Exception as e:
        return {"reply": f"EcoBot Error: {e}"}

#user connection
@app.route('/request_connection/<item_id>')
def request_connection(item_id):
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))

    # Get location from query string (sent via JS or button click)
    lat_str = request.args.get('lat')
    lon_str = request.args.get('lon')

    if not (lat_str and lon_str):
        flash("Location not provided. Please allow location access.", "error")
        return redirect(url_for('my_items'))

    try:
        lat = float(lat_str)
        lon = float(lon_str)
    except ValueError:
        flash("Invalid location data.", "error")
        return redirect(url_for('my_items'))

    # Get the item info
    item = db.items.find_one({"_id": ObjectId(item_id)})
    if not item:
        flash("Item not found.", "error")
        return redirect(url_for('my_items'))

    material_type = item.get('material_type', '').lower()

    # Find the nearest center that accepts the material type
    pipeline = [
        {
            "$geoNear": {
                "near": {"type": "Point", "coordinates": [lon, lat]},
                "distanceField": "distance",
                "spherical": True
            }
        },
        {
            "$match": {
                "acceptedItems": {"$elemMatch": {"$regex": material_type, "$options": "i"}}
            }
        },
        {"$sort": {"distance": 1}},
        {"$limit": 1}
    ]

    center = list(db.recyclingCenters.aggregate(pipeline))
    if not center:
        flash("No recycling center nearby accepts this item.", "error")
        return redirect(url_for('my_items'))

    closest_center = center[0]
    center_id = str(closest_center['_id'])

    # Update item status
    db.items.update_one(
        {"_id": ObjectId(item_id)},
        {"$set": {
            "status": "Connection Requested",
            "centerId": center_id
        }}
    )

    flash(f"✅ Request sent to nearby center: {closest_center['name']}")
    return redirect(url_for('my_items'))

@app.route('/center/login', methods=['GET', 'POST'])
def center_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        center = db.center_logins.find_one({"email": email})
        if center:
            if center.get("status") == "Rejected":
                flash("❌ Your signup request was rejected by admin.", "error")
                return redirect(url_for('center_login'))

            if not center.get("verified"):
                flash("⏳ Your account is pending admin approval.", "warning")
                return redirect(url_for('center_login'))

            if bcrypt.checkpw(password.encode('utf-8'), center['password']):
                session['center_id'] = str(center['centerId'])
                session['center_name'] = center['name']
                return redirect(url_for('center_dashboard'))

        flash("Invalid login credentials.", "error")
        return redirect(url_for('center_login'))

    return render_template('center_login.html')


@app.route('/center/signup', methods=['GET', 'POST'])
def center_signup():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm')

        if password != confirm:
            flash("Passwords do not match!", "error")
            return redirect(url_for('center_signup'))

        existing = db.center_logins.find_one({"email": email})
        if existing:
            flash("Center with this email already exists.", "error")
            return redirect(url_for('center_signup'))

        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        center_id = db.recyclingCenters.insert_one({
            "name": name,
            "address": "",
            "acceptedItems": [],
            "location": None,
            "image": None,
            "createdAt": datetime.now().strftime("%Y-%m-%d")
        }).inserted_id

        db.center_logins.insert_one({
            "email": email,
            "password": hashed_pw,
            "centerId": center_id,
            "name": name,
            "verified": False,
            "status": "Pending"
        })

        flash("Signup successful! Your request has been sent for admin approval.", "info")
        return redirect(url_for('center_login'))

    return render_template("center_signup.html")

def center_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'center_id' not in session:
            flash("Please log in as a center to access that page.", "warning")
            return redirect(url_for('center_login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/center/dashboard')
@center_required
def center_dashboard():
    center_id = session['center_id']
    center = db.recyclingCenters.find_one({"_id": ObjectId(center_id)})

    total_items = db.connected_items.count_documents({"centerId": ObjectId(center_id)})
    approved_items = db.connected_items.count_documents({"centerId": ObjectId(center_id), "status": "Approved"})
    pending_items = db.connected_items.count_documents({"centerId": ObjectId(center_id), "status": "Pending"})

    return render_template(
        'center_dashboard.html',
        center=center,
        total_items=total_items,
        approved_items=approved_items,
        pending_items=pending_items
    )


#admin verification
@app.route('/admin/verify_centers')
@admin_required
def admin_verify_centers():
    centers = list(db.center_logins.find({
        "$or": [
            {"verified": False},
            {"verified": {"$exists": False}}
        ],
        "status": {"$ne": "Rejected"}
    }))
    for center in centers:
        center['_id'] = str(center['_id'])
    return render_template('admin_verify_centers.html', centers=centers)



@app.route('/admin/verify_center/<center_id>', methods=['POST'])
@admin_required
def approve_center(center_id):
    db.center_logins.update_one(
        {"_id": ObjectId(center_id)},
        {"$set": {"verified": True, "status": "Approved"}}
    )
    flash("Center approved successfully!", "success")
    return redirect(url_for('admin_verify_centers'))



@app.route('/admin/reject_center/<center_id>', methods=['POST'])
@admin_required
def reject_center(center_id):
    db.center_logins.update_one(
        {"_id": ObjectId(center_id)},
        {"$set": {"status": "Rejected"}}
    )
    flash("Center rejected.", "info")
    return redirect(url_for('admin_verify_centers'))


@app.route('/center/update_profile', methods=['GET', 'POST'])
def update_center_profile():
    if 'center_id' not in session:
        flash("Please log in as a center.")
        return redirect(url_for('center_login'))

    center_id = session['center_id']
    center_obj = db.recyclingCenters.find_one({"_id": ObjectId(center_id)})

    if request.method == 'POST':
        name = request.form.get("name")
        address = request.form.get("address")
        accepted_items = request.form.get("accepted_items")
        location_type = request.form.get("location_type")
        location = None

        if location_type == "live":
            coords = request.form.get("location").split(",")
            if len(coords) == 2:
                location = {"type": "Point", "coordinates": [float(coords[1]), float(coords[0])]}
        elif location_type == "custom":
            lat = request.form.get("latitude")
            lon = request.form.get("longitude")
            if lat and lon:
                location = {"type": "Point", "coordinates": [float(lon), float(lat)]}

        # Handle image
        image_file = request.files.get("image")
        image_path = center_obj.get("image")
        if image_file and image_file.filename != "":
            filename = secure_filename(image_file.filename)
            image_path = "uploads/" + filename
            image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        update_request = {
            "centerId": ObjectId(center_id),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "new_data": {
                "name": name,
                "address": address,
                "acceptedItems": [i.strip() for i in accepted_items.split(",")],
                "image": image_path,
                "location": location
            },
            "status": "Pending"
        }

        db.center_update_requests.update_one(
            {"centerId": ObjectId(center_id)},
            {"$set": update_request},
            upsert=True
        )

        flash("Your update request has been submitted and is pending admin approval.", "success")
        return redirect(url_for('update_center_profile'))

    # Check for rejection status
    request_doc = db.center_update_requests.find_one({"centerId": ObjectId(center_id)})
    if request_doc and request_doc.get("status") == "Rejected":
        flash("⚠️ Your last update request was rejected. Please submit again.", "danger")

    # Render form
    center_data = {
        "name": center_obj.get("name", ""),
        "address": center_obj.get("address", ""),
        "accepted_items": ", ".join(center_obj.get("acceptedItems", [])),
        "location": center_obj.get("location", "")
    }
    return render_template("update_profile.html", center=center_data)

@app.route('/admin/center_updates')
@admin_required
def admin_center_updates():
    requests = list(db.center_update_requests.find({"status": "Pending"}))
    updates = []
    for req in requests:
        center = db.recyclingCenters.find_one({"_id": req["centerId"]})
        updates.append({
            "_id": str(req["_id"]),
            "centerId": str(req["centerId"]),
            "old": center,
            "new": req["new_data"]
        })
    return render_template("admin_center_updates.html", updates=updates)


@app.route('/admin/center_updates/approve/<req_id>', methods=['POST'])
@admin_required
def approve_center_update(req_id):
    request_doc = db.center_update_requests.find_one({"_id": ObjectId(req_id)})
    if request_doc:
        db.recyclingCenters.update_one(
            {"_id": request_doc["centerId"]},
            {"$set": request_doc["new_data"]}
        )
        db.center_update_requests.delete_one({"_id": ObjectId(req_id)})
        flash("Center profile update approved.", "success")
    return redirect(url_for('admin_center_updates'))


@app.route('/admin/center_updates/reject/<req_id>', methods=['POST'])
@admin_required
def reject_center_update(req_id):
    db.center_update_requests.delete_one({"_id": ObjectId(req_id)})
    flash("Center profile update rejected.", "info")
    return redirect(url_for('admin_center_updates'))

@app.route('/connect_centers/<item_id>')
def connect_centers(item_id):
    if 'user_id' not in session:
        flash("Please log in.")
        return redirect(url_for('login'))

    item = db.items.find_one({"_id": ObjectId(item_id)})
    if not item:
        flash("Item not found.")
        return redirect(url_for('scan_item'))

    user_lat = request.args.get('lat')
    user_lon = request.args.get('lon')

    if not user_lat or not user_lon:
        flash("Location missing.")
        return redirect(url_for('scan_item'))

    try:
        lat = float(user_lat)
        lon = float(user_lon)
    except:
        flash("Invalid coordinates.")
        return redirect(url_for('scan_item'))

    # Just get all centers within 50km, don't filter by item type
    pipeline = [
        {
            "$geoNear": {
                "near": {"type": "Point", "coordinates": [lon, lat]},
                "distanceField": "distance",
                "maxDistance": 50000,
                "spherical": True
            }
        }
    ]
    centers = list(db.recyclingCenters.aggregate(pipeline))
    for center in centers:
        center['_id'] = str(center['_id'])
    return render_template("nearby_centers.html", centers=centers, item_id=item_id)

@app.route('/send_connection/<item_id>/<center_id>', methods=['POST'])
def send_connection_request(item_id, center_id):
    if 'user_id' not in session:
        flash("Please log in.")
        return redirect(url_for('login'))

    item = db.items.find_one({"_id": ObjectId(item_id)})
    if not item:
        flash("Item not found.")
        return redirect(url_for('scan_item'))

    # Prevent duplicate requests
    exists = db.connected_items.find_one({
        "itemId": ObjectId(item_id),
        "centerId": ObjectId(center_id)
    })
    if exists:
        flash("Request already sent to this center.")
        return redirect(url_for('my_items'))

    db.connected_items.insert_one({
        "itemId": ObjectId(item_id),
        "centerId": ObjectId(center_id),
        "userId": session['user_id'],
        "material_type": item.get("material_type", ""),
        "estimated_value": item.get("estimated_value", ""),
        "status": "Pending",
        "timestamp": time.strftime("%Y-%m-%d")
    })

    flash("Request sent successfully!")
    return redirect(url_for('my_items'))

@app.route('/center/requests', methods=['GET', 'POST'])
@center_required
def center_requests():
    center_id = ObjectId(session['center_id'])

    if request.method == 'POST':
        connection_id = request.form.get('connection_id')
        material_type = request.form.get('material_type')
        estimated_value = request.form.get('estimated_value')
        status = request.form.get('status')
        feedback = request.form.get('feedback')

        # Update connected_items collection
        db.connected_items.update_one(
            {"_id": ObjectId(connection_id)},
            {
                "$set": {
                    "material_type": material_type,
                    "estimated_value": estimated_value,
                    "status": status,
                    "feedback": feedback
                }
            }
        )

        # Also update the original items collection status to 'Recycled' if approved
        if status == "Approved":
            conn = db.connected_items.find_one({"_id": ObjectId(connection_id)})
            if conn and 'itemId' in conn:
                db.items.update_one(
                    {"_id": ObjectId(conn['itemId'])},
                    {"$set": {"status": "Recycled"}}
                )

        flash("Item updated successfully.", "success")
        return redirect(url_for('center_requests'))

    # --- GET method display ---
    connections = list(db.connected_items.find(
        {"centerId": center_id, "status": "Pending"},
        {
            "_id": 1,
            "material_type": 1,
            "estimated_value": 1,
            "status": 1,
            "feedback": 1,
            "itemId": 1,
            "timestamp": 1
        }
    ))

    # Fetch corresponding item details without loading huge fields
    for conn in connections:
        item = db.items.find_one({"_id": conn["itemId"]}, {
            "material_type": 1,
            "estimated_value": 1,
            "image_path": 1,
            "reason": 1
        })
        conn["item"] = item

    return render_template("center_requests.html", requests=connections)




@app.route('/update_connection_status/<req_id>', methods=['POST'])
@center_required
def update_connection_status(req_id):
    status = request.form.get('status')
    feedback = request.form.get('feedback')
    material_type = request.form.get('material_type')
    estimated_value = float(request.form.get('estimated_value'))
    item_id = ObjectId(request.form.get('itemId'))

    # Update the connected_items document
    db.connected_items.update_one(
        {"_id": ObjectId(req_id)},
        {"$set": {
            "status": status,
            "material_type": material_type,
            "estimated_value": estimated_value,
            "feedback": feedback
        }}
    )

    # Update the item document too
    db.items.update_one(
        {"_id": item_id},
        {"$set": {
            "status": status,
            "material_type": material_type,
            "estimated_value": estimated_value,
            "center_feedback": feedback
        }}
    )

    # If approved, add rewards to user account
    if status == "Approved":
        connected = db.connected_items.find_one({"_id": ObjectId(req_id)})
        user_id = connected['userId']
        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"rewards": estimated_value}}
        )
        
        # ✅ Also increment items_recycled
        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"items_recycled": 1}}
        )

    flash(f"✅ Request updated and marked as {status}.")
    return redirect(url_for('center_requests'))

@app.route('/center/approved_items')
@center_required
def center_approved_items():
    center_id = session['center_id']
    
    approved_data = list(db.connected_items.find({
        "centerId": ObjectId(center_id),
        "status": "Approved"
    }))

    for req in approved_data:
        item = db.items.find_one({"_id": req["itemId"]})
        req["item"] = item

    return render_template("center_approved_items.html", approved_data=approved_data)

@app.route('/leaderboard')
def leaderboard():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))

    # Sort users by rewards descending
    top_users = list(db.users.find().sort("rewards", -1))

    # Get current user
    current_user_doc = db.users.find_one({"_id": ObjectId(session['user_id'])})

    if not current_user_doc:
        flash("User not found.")
        return redirect(url_for('login'))

    current_user_name = current_user_doc['name']
    current_user_rewards = current_user_doc.get('rewards', 0)
    current_user_items = current_user_doc.get('items_recycled', 0)

    # Find current user's rank
    user_rank = None
    for idx, user in enumerate(top_users):
        if user['name'] == current_user_name:
            user_rank = idx + 1
            break

    return render_template('leaderboard.html',top_users=top_users,current_user=current_user_name,user_rank=user_rank,user_rewards=current_user_rewards,user_items=current_user_items)

@app.route('/user_dashboard')
def user_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('user_dashboard.html')

@app.route('/user_dashboard/data', methods=['POST'])
def user_dashboard_data():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    from_date = datetime.strptime(data['from_date'], '%Y-%m-%d')
    to_date = datetime.strptime(data['to_date'], '%Y-%m-%d')

    user_id = session['user_id']

    # --- REWARDS CUMULATIVE CALCULATION (Items + Withdrawals) ---
    cumulative_rewards = {}
    running_total = 0

    # Fetch all item rewards
    item_cursor = db.connected_items.find({
        "userId": user_id,
        "status": "Approved",
        "timestamp": {"$gte": from_date.strftime("%Y-%m-%d"), "$lte": to_date.strftime("%Y-%m-%d")}
    })

    for item in item_cursor:
        date = item['timestamp']
        value = float(item.get('estimated_value', 0))
        cumulative_rewards[date] = cumulative_rewards.get(date, 0) + value

    # Fetch all withdrawals
    withdrawal_cursor = db.transactions.find({
        "userId": user_id,
        "transactionDate": {"$gte": from_date.strftime("%Y-%m-%d"), "$lte": to_date.strftime("%Y-%m-%d")}
    })

    for withdrawal in withdrawal_cursor:
        date = withdrawal['transactionDate']
        value = float(withdrawal.get('redeemAmount', 0))
        cumulative_rewards[date] = cumulative_rewards.get(date, 0) - value

    # Sort by date for cumulative summation
    sorted_dates = sorted(cumulative_rewards.keys())
    cumulative_sum = []
    total = 0
    for d in sorted_dates:
        total += cumulative_rewards[d]
        cumulative_sum.append(total)

    rewards = {
        "labels": sorted_dates,
        "datasets": [{
            "label": "Cumulative Rewards ($)",
            "data": cumulative_sum,
            "backgroundColor": "rgba(46, 125, 50, 0.2)",
            "borderColor": "#2e7d32",
            "fill": True,
            "tension": 0.3
        }]
    }

    # --- ITEMS Data ---
    items_data = {}
    items_cursor = db.connected_items.find({
        "userId": user_id,
        "status": "Approved",
        "timestamp": {"$gte": from_date.strftime("%Y-%m-%d"), "$lte": to_date.strftime("%Y-%m-%d")}
    })

    for item in items_cursor:
        day = item.get('timestamp')
        if day:
            items_data[day] = items_data.get(day, 0) + 1

    items = {
        "labels": list(items_data.keys()),
        "datasets": [{
            "label": "Items Recycled",
            "data": list(items_data.values()),
            "backgroundColor": "#66bb6a"
        }]
    }

    # --- MATERIALS Data ---
    materials_count = {}
    materials_cursor = db.connected_items.find({
        "userId": user_id,
        "status": "Approved",
        "timestamp": {"$gte": from_date.strftime("%Y-%m-%d"), "$lte": to_date.strftime("%Y-%m-%d")}
    })

    for mat in materials_cursor:
        mtype = mat.get('material_type', 'Unknown')
        materials_count[mtype] = materials_count.get(mtype, 0) + 1

    materials = {
        "labels": list(materials_count.keys()),
        "datasets": [{
            "label": "Materials",
            "data": list(materials_count.values()),
            "backgroundColor": [
                "#66bb6a", "#42a5f5", "#ffca28", "#ef5350", "#ab47bc", "#26a69a"
            ]
        }]
    }

    return jsonify({
        "rewards": rewards,
        "items": items,
        "materials": materials
    })

# ========== Admin Graph Page ==========
@app.route('/admin_graph')
def admin_graph():
    if 'is_admin' not in session or not session['is_admin']:
        flash("Admin access required!", "danger")
        return redirect(url_for('login'))
    return render_template('admin_graph.html')

# ========== Admin Graph Data API ==========
@app.route('/admin_graph/data', methods=['POST'])
def admin_graph_data():
    if 'is_admin' not in session or not session['is_admin']:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    from_date = datetime.strptime(data['from_date'], '%Y-%m-%d')
    to_date = datetime.strptime(data['to_date'], '%Y-%m-%d')

    from_date_str = from_date.strftime("%Y-%m-%d")
    to_date_str = to_date.strftime("%Y-%m-%d")

    # --- 1. Users Growth Over Time ---
    user_growth = {}
    users = db.users.find()

    for user in users:
        date = user.get('createdAt') or user.get('registeredDate')
        if date:
            date = date.split('T')[0] if 'T' in date else date
            if from_date_str <= date <= to_date_str:
                user_growth[date] = user_growth.get(date, 0) + 1

    sorted_user_growth = dict(sorted(user_growth.items()))
    cumulative_users = []
    total_users = 0
    for d in sorted_user_growth:
        total_users += sorted_user_growth[d]
        cumulative_users.append(total_users)

    users_growth = {
        "labels": list(sorted_user_growth.keys()),
        "datasets": [{
            "label": "Total Users",
            "data": cumulative_users,
            "borderColor": "#42a5f5",
            "backgroundColor": "rgba(66, 165, 245, 0.2)",
            "fill": True,
            "tension": 0.3
        }]
    }

    # --- 2. Centers Growth Over Time ---
    center_growth = {}
    centers = db.recyclingCenters.find()

    for center in centers:
        date = center.get('createdAt')
        if date:
            date = date.split('T')[0] if 'T' in date else date
            if from_date_str <= date <= to_date_str:
                center_growth[date] = center_growth.get(date, 0) + 1

    sorted_center_growth = dict(sorted(center_growth.items()))
    cumulative_centers = []
    total_centers = 0
    for d in sorted_center_growth:
        total_centers += sorted_center_growth[d]
        cumulative_centers.append(total_centers)

    centers_growth = {
        "labels": list(sorted_center_growth.keys()),
        "datasets": [{
            "label": "Total Centers",
            "data": cumulative_centers,
            "borderColor": "#66bb6a",
            "backgroundColor": "rgba(102, 187, 106, 0.2)",
            "fill": True,
            "tension": 0.3
        }]
    }

    # --- 3. Items Uploaded ---
    items_uploaded = {}
    items = db.connected_items.find({"status": "Approved"})

    for item in items:
        date = item.get('timestamp')
        if date:
            date = date.split('T')[0] if 'T' in date else date
            if from_date_str <= date <= to_date_str:
                items_uploaded[date] = items_uploaded.get(date, 0) + 1

    sorted_items_uploaded = dict(sorted(items_uploaded.items()))

    items_uploaded_chart = {
        "labels": list(sorted_items_uploaded.keys()),
        "datasets": [{
            "label": "Items Uploaded",
            "data": list(sorted_items_uploaded.values()),
            "backgroundColor": "#ffa726"
        }]
    }

    # --- 4. Transactions (Redeemed vs Remaining) ---
    total_redeemed = 0
    redeemed_tx = db.transactions.find({
        "transactionType": "Redeem",
        "transactionDate": {"$gte": from_date_str, "$lte": to_date_str}
    })
    for tx in redeemed_tx:
        total_redeemed += float(tx.get('redeemAmount', 0))

    total_remaining = 0
    users_cursor = db.users.find()
    for user in users_cursor:
        total_remaining += float(user.get('rewards', 0))

    transactions_split = {
        "labels": ["Redeemed", "Remaining"],
        "datasets": [{
            "label": "Rewards",
            "data": [total_redeemed, total_remaining],
            "backgroundColor": ["#66bb6a", "#42a5f5"]
        }]
    }

    return jsonify({
        "users_growth": users_growth,
        "centers_growth": centers_growth,
        "items_uploaded": items_uploaded_chart,
        "transactions_split": transactions_split
    })
def add_transaction(user_id, tx_type, amount):
    transaction = {
        "userId": user_id,
        "transactionDate": time.strftime("%Y-%m-%d")
    }
    
    if tx_type == "reward":
        transaction["type"] = "reward"
        transaction["totalEarnings"] = amount
    elif tx_type == "withdrawal":
        transaction["type"] = "withdrawal"
        transaction["amount"] = amount
    else:
        raise ValueError("Invalid transaction type!")

    db.transactions.insert_one(transaction)


if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    app.run(debug=True)

# ollama run llava