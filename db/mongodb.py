from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
import datetime


#CLOUD
MONGO_URI = "mongodb+srv://mytkavish:XXXXXXX@cluster0.z8s2k.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client["air_pollution_db"]

#LOCALDB
def get_db():
    #client = MongoClient("mongodb://localhost:27017/")
   # db = client["air_pollution"]
    return client["air_pollution_db"]

### 1. Storing Air Pollution Data ###
def store_sensor_data(data):
   # client = MongoClient("mongodb://localhost:27017/")  # ❌ Still using local MongoDB
    #db = client.air_pollution
    db = get_db()

    # Fix: Ensure PM2.5 is stored without quotes
    data["timestamp"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    data["PM2.5"] = float(data.get("PM2.5", 0))  # Ensures correct field name
    data["PM10"] = float(data.get("PM10", 0))

    print("Storing Data:", data)  # Debugging output

    db.pollution_data.insert_one(data)


### 2. Creating Users Collection ###
def create_users_collection():
    db = get_db()
    users_collection = db["users"]

    # Ensure unique emails
    users_collection.create_index("email", unique=True)

    return users_collection


### 3. Registering a New User ###
def register_user_api(email, password, user_type):
    db = get_db()
    users_collection = db["users"]

    # Hash the password before storing
    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

    user_data = {
        "email": email,
        "password": hashed_password,
        "user_type": user_type,
        "is_active": False  # Users are inactive until admin activates them
    }

    try:
        users_collection.insert_one(user_data)
        return True, "User registered successfully. Please wait for admin approval."
    except Exception as e:
        return False, f"Error: {e}"



### 4. Authenticating a User ###
def authenticate_user(email, password):
    db = get_db()
    users_collection = db["users"]

    user = users_collection.find_one({"email": email})

    if user and check_password_hash(user["password"], password):
        if not user["is_active"]:
            return False, "inactive"  # Prevent login for inactive users
        return True, user["user_type"]

    return False, None

### 5. Storing Blockchain data ###

def create_blockchain_collection():
    db = get_db()
    if "blockchain" not in db.list_collection_names():
        db.create_collection("blockchain")
