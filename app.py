
import os
import time
import json
import base64  # <-- IMPORTANT: import base64 to fix the undefined error
from functools import wraps
from flask import Flask, render_template, request, url_for, redirect, flash, session
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
    user_transactions = db.transactions.find({"userId": user_id})
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
        # Or you could have a "payment_method" dropdown, etc.

        # Validate the fields (simple example)
        if not (bank_name and account_number and ifsc_code):
            flash("Please fill all payment details.")
            return redirect(url_for('redeem_details'))

        # Double-check user still has enough points
        if redeem_value > current_rewards:
            flash("You no longer have enough rewards to redeem that amount.")
            return redirect(url_for('redeem_rewards'))

        # Deduct points from user
        db.users.update_one(
            {"_id": ObjectId(session['user_id'])},
            {"$inc": {"rewards": -redeem_value}}
        )

        # Insert redemption transaction
        tx_id = db.transactions.insert_one({
            "userId": session['user_id'],
            "transactionDate": time.strftime("%Y-%m-%d"),
            "type": "redeem",
            "redeemAmount": redeem_value,
            "paymentInfo": {
                "bankName": bank_name,
                "accountNumber": account_number,
                "ifscCode": ifsc_code
            }
        }).inserted_id

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
from bson import ObjectId

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
    test_email = "greenit@example.com"
    if not db.center_logins.find_one({"email": test_email}):
        test_center = db.recyclingCenters.find_one({"name": {"$regex": "green", "$options": "i"}})
        if test_center:
            db.center_logins.insert_one({
                "email": test_email,
                "password": bcrypt.hashpw("center123".encode('utf-8'), bcrypt.gensalt()),
                "centerId": test_center["_id"],
                "name": test_center["name"],
                "role": "center"
            })

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        center = db.center_logins.find_one({"email": email})
        if center and bcrypt.checkpw(password.encode('utf-8'), center['password']):
            session.clear()
            session['center_id'] = str(center['centerId'])
            session['center_name'] = center['name']
            flash("Center login successful!", "success")
            return redirect(url_for('center_dashboard'))

        flash("Invalid center login credentials!", "error")
        return redirect(url_for('center_login'))

    return render_template("center_login.html")

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

        # Create recycling center entry
        center_id = db.recyclingCenters.insert_one({
            "name": name,
            "address": "",
            "acceptedItems": [],
            "location": None,
            "image": None
        }).inserted_id

        # Create login entry
        db.center_logins.insert_one({
            "email": email,
            "password": bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()),
            "centerId": center_id,
            "name": name,
            "role": "center"
        })

        session.clear()
        session['center_id'] = str(center_id)
        session['center_name'] = name
        flash("Center account created successfully!", "success")
        return redirect(url_for('center_dashboard'))

    return render_template("center_signup.html")



@app.route('/center/dashboard')
def center_dashboard():
    if 'center_id' not in session:
        flash("Please log in as a center.")
        return redirect(url_for('center_login'))

    center_name = session.get('center_name', 'Center')
    return Markup(f"<h2>Welcome, <b>{center_name}</b></h2><p>Your center dashboard will appear here.</p>")


if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    app.run(debug=True)
