from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash


def get_db():
    client = MongoClient("mongodb://localhost:27017/")
    db = client["air_pollution"]
    return db


### 1. Storing Air Pollution Data ###
def store_sensor_data(data):
    db = get_db()
    db.pollution_data.insert_one(data)


### 2. Creating Users Collection ###
def create_users_collection():
    db = get_db()
    users_collection = db["users"]

    # Ensure unique emails
    users_collection.create_index("email", unique=True)

    return users_collection


### 3. Registering a New User ###
def register_user(email, password, user_type):
    db = get_db()
    users_collection = db["users"]

    # Hash the password before storing
    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

    user_data = {
        "email": email,
        "password": hashed_password,  # Securely hashed password
        "user_type": user_type  # Values: admin, home_user, kid_user
    }

    try:
        users_collection.insert_one(user_data)
        return True, "User registered successfully"
    except Exception as e:
        return False, f"Error: {e}"


### 4. Authenticating a User ###
def authenticate_user(email, password):
    db = get_db()
    users_collection = db["users"]

    user = users_collection.find_one({"email": email})

    if user and check_password_hash(user["password"], password):
        return True, user["user_type"]

    return False, None
