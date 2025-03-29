from flask import Flask, render_template, request, url_for, redirect, flash, session
from pymongo import MongoClient
from config import DB_URL
import bcrypt
from bson import ObjectId

client = MongoClient(DB_URL)
db = client['ecoearn']  # using the "ecoearn" database

app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # required for flash messages and sessions

# 1) Landing page (index.html)
@app.route('/')
def index():
    return render_template('index.html')

# 2) Signup page
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        # Get form data
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        terms = request.form.get('terms')

        # Must agree to terms
        if not terms:
            flash("You must agree to the terms and policy!")
            return redirect(url_for('signup'))

        # Check if user already exists
        existing_user = db.users.find_one({"email": email})
        if existing_user:
            flash("Email already registered. Please log in.")
            return redirect(url_for('login'))

        # Hash the password
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        # Insert new user document into MongoDB
        db.users.insert_one({
            "name": name,
            "email": email,
            "password": hashed,
            "rewards": 0,          # example field
            "items_recycled": 0    # example field
        })

        flash("Signup successful! Please log in.")
        return redirect(url_for('login'))

    return render_template('signup.html')

# 3) Login page
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        # Find user in the database
        user = db.users.find_one({"email": email})
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password']):
            # Store user id in session for authentication
            session['user_id'] = str(user['_id'])
            flash("Login successful!")
            # Redirect to the main home screen
            return redirect(url_for('home'))
        else:
            flash("Invalid email or password!")
            return redirect(url_for('login'))

    return render_template('login.html')

# 4) Main Home Screen / Dashboard (requires login)
@app.route('/home')
def home():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = db.users.find_one({"_id": ObjectId(user_id)})

    # You can do additional queries or calculations here, for example:
    # transactions = list(db.transactions.find({"userId": user["_id"]}))
    # total_items, total_rewards, etc. = some calculation

    return render_template('home.html', user=user)

# 5) Logout route
@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully!")
    return redirect(url_for('login'))

# -------------------------
# 6) Placeholder routes for future features
# (You can remove or implement these as needed)

@app.route('/scan_item')
def scan_item():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    return render_template('scan_item.html')  # Create this template if needed

@app.route('/recycling_centers')
def recycling_centers():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    return render_template('recycling_centers.html')  # Create this template if needed

@app.route('/transactions')
def transactions():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    return render_template('transactions.html')  # Create this template if needed

if __name__ == '__main__':
    app.run(debug=True)
