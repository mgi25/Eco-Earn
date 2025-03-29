from flask import Flask, render_template, request, url_for, redirect, flash, session
from pymongo import MongoClient
from config import DB_URL
import bcrypt

client = MongoClient(DB_URL)
db = client['ecoearn']  # using the "ecoearn" database

app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # required for flash messages and sessions

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        # Get form data
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        terms = request.form.get('terms')
        
        # Ensure the user agreed to terms
        if not terms:
            flash("You must agree to the terms and policy!")
            return redirect(url_for('signup'))
        
        # Check if the user already exists
        existing_user = db.users.find_one({"email": email})
        if existing_user:
            flash("Email already registered. Please log in.")
            return redirect(url_for('login'))
        
        # Hash the password using bcrypt
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        # Insert the new user into the "users" collection
        db.users.insert_one({
            "name": name,
            "email": email,
            "password": hashed
        })
        
        flash("Signup successful! Please log in.")
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Retrieve the user document from MongoDB
        user = db.users.find_one({"email": email})
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password']):
            session['user_id'] = str(user['_id'])
            flash("Login successful!")
            return redirect(url_for('index'))
        else:
            flash("Invalid email or password!")
            return redirect(url_for('login'))
    return render_template('login.html')

if __name__ == '__main__':
    app.run(debug=True)
