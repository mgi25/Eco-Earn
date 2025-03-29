from flask import Flask, render_template, request, url_for, redirect
from pymongo import MongoClient
from config import DB_URL
from bson import ObjectId

client = MongoClient(DB_URL)
db = client['ecoearn']

app = Flask(__name__)

@app.route('/')
def index():
    return "<h1>Welcome to Eco-Earn</h1>"

@app.route('/signup')
def signup():
    return render_template('signup.html')

# NEW: Login route
@app.route('/login')
def login():
    return render_template('login.html')

if __name__ == '__main__':
    app.run(debug=True)
