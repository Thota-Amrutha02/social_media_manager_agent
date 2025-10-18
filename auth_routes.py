from flask import Blueprint, request, jsonify
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
import traceback

# Load environment variables
load_dotenv()

# MongoDB setup (reuse your existing connection string)
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["social_media_manager"]
users_collection = db["instausers"]

# Create Blueprint
auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/signup", methods=["POST"])
def signup():
    try:
        data = request.json
        username = data.get("username")
        password = data.get("password")
        instagram_token = data.get("instagram_token", None)

        if not username or not password:
            return jsonify({"success": False, "message": "Username and password required"}), 400

        if users_collection.find_one({"username": username}):
            return jsonify({"success": False, "message": "User already exists"}), 400

        hashed_pw = generate_password_hash(password)
        users_collection.insert_one({
            "username": username,
            "password": hashed_pw,
            "instagram_token": instagram_token
        })

        return jsonify({"success": True, "message": "User registered successfully"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@auth_bp.route("/login", methods=["POST"])
def login():
    try:
        data = request.json
        username = data.get("username")
        password = data.get("password")

        user = users_collection.find_one({"username": username})
        if not user or not check_password_hash(user["password"], password):
            return jsonify({"success": False, "message": "Invalid credentials"}), 401

        return jsonify({
            "success": True,
            "message": "Login successful",
            "user": {"username": user["username"], "instagram_token": user.get("instagram_token")}
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
