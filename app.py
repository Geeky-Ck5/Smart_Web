from flask import Flask, render_template, jsonify, request, redirect, session, flash
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from functools import wraps
from db.mongodb import store_sensor_data, register_user_api, authenticate_user, create_users_collection, get_db
from blockchain.blockchain import Blockchain
import datetime
import os
import requests


app = Flask(__name__)
app.secret_key = os.urandom(24)  # Generate a new secret key every restart (forces session reset)
app.config['SESSION_PERMANENT'] = False  # Ensure sessions expire when the app closes

BOT_SLEEP_TIME=5

blockchain = Blockchain()
air_pollution_data = []  # Stores real-time pollution data

# Ensure users collection exists
create_users_collection()

### Authentication Helper Function ###
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("x-access-token")

        if not token:
            return jsonify({"error": "Token is missing"}), 401

        try:
            data = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
            current_user = get_db().users.find_one({"email": data["email"]})

            if not current_user:
                return jsonify({"error": "Invalid token"}), 401

        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        return f(current_user, *args, **kwargs)

    return decorated


### Fetch Sensor Data and Store in MongoDB ###
def fetch_sensor_data():
    global air_pollution_data
    response = requests.get("http://127.0.0.1:5001/sensor")
    data = response.json()
    air_pollution_data.append(data)

    # Store sensor data in MongoDB
    store_sensor_data(data)

    # Store in Blockchain
    blockchain.add_block(data)

### Activate Actuator API ###
@app.route("/activate_actuator", methods=["POST"])
def activate_actuator():
    """Allows an admin to manually activate the actuator if PM10 is in amber range."""
    if "user_type" not in session or session["user_type"] != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    pm10_value = float(request.form.get("pm10_value", 0))
    timestamp = request.form.get("timestamp", "")

    if 80 <= pm10_value <= 100:
        try:
            response = requests.post("http://127.0.0.1:5002/actuator", json={"PM10": pm10_value, "manual": True})
            return redirect("/admin")  # Redirect to Admin Panel after activation
        except requests.exceptions.RequestException as e:
            return f"Error triggering actuator: {e}", 500
    else:
        return jsonify({"error": "PM10 value is not in the amber range (80-100)."}), 400



### Store Weekly Summary in Blockchain ###
def store_weekly_summary():
    global air_pollution_data

    if len(air_pollution_data) == 0:
        return

    total_pm25 = sum(entry["PM2.5"] for entry in air_pollution_data)
    total_pm10 = sum(entry["PM10"] for entry in air_pollution_data)
    avg_pm25 = round(total_pm25 / len(air_pollution_data), 2)
    avg_pm10 = round(total_pm10 / len(air_pollution_data), 2)

    summary = {
        "week_start": str(datetime.datetime.utcnow() - datetime.timedelta(days=7)),
        "week_end": str(datetime.datetime.utcnow()),
        "avg_PM2.5": avg_pm25,
        "avg_PM10": avg_pm10,
        "data_points": len(air_pollution_data)
    }

    blockchain.add_block(summary)
    air_pollution_data = []


### Start Schedulers ###
scheduler = BackgroundScheduler()
scheduler.add_job(fetch_sensor_data, "interval", seconds=30)
scheduler.add_job(store_weekly_summary, "interval", weeks=1)
scheduler.start()


### Flask Web Routes ###
@app.route("/")
def index():
    if "user_type" in session:
        return redirect("/dashboard") if session["user_type"] == "admin" else f"Welcome, {session['user_type']}!"
    return render_template("index.html", data=air_pollution_data)


@app.route("/dashboard")
def dashboard():
    if "user_type" not in session:
        return redirect("/login")

    user_role = session["user_type"]
    db = get_db()

    pollution_data = list(db.pollution_data.find({}, {"_id": 0}).sort("timestamp", -1).limit(10))
    blockchain_data = blockchain.get_chain()[-10:]

    total_pollution = db.pollution_data.count_documents({})
    total_blocks = len(blockchain_data)

    pm25_threshold = 100
    pm10_threshold = 150

    pm25_threshold_count = db.pollution_data.count_documents({"PM2.5": {"$gt": pm25_threshold}})
    pm10_threshold_count = db.pollution_data.count_documents({"PM10": {"$gt": pm10_threshold}})
    actuator_count = pm25_threshold_count + pm10_threshold_count

    # Fetch Highest PM2.5 & PM10 Values (Fix Field Name Issues)
    highest_pm25_doc = db.pollution_data.find_one({"PM2.5": {"$exists": True}}, sort=[("PM2.5", -1)],
                                                  projection={"PM2.5": 1, "timestamp": 1})
    highest_pm10_doc = db.pollution_data.find_one({"PM10": {"$exists": True}}, sort=[("PM10", -1)],
                                                  projection={"PM10": 1, "timestamp": 1})

    highest_pm25 = highest_pm25_doc["PM2.5"] if highest_pm25_doc else "No Data"
    highest_pm25_timestamp = highest_pm25_doc["timestamp"] if highest_pm25_doc else "No Data"

    highest_pm10 = highest_pm10_doc["PM10"] if highest_pm10_doc else "No Data"
    highest_pm10_timestamp = highest_pm10_doc["timestamp"] if highest_pm10_doc else "No Data"

    return render_template(
        "dashboard.html",
        data=pollution_data, blockchain_data=blockchain_data,
        total_pollution=total_pollution, total_blocks=total_blocks,
        pm25_threshold_count=pm25_threshold_count, pm10_threshold_count=pm10_threshold_count,
        actuator_count=actuator_count,
        highest_pm25=highest_pm25, highest_pm25_timestamp=highest_pm25_timestamp,
        highest_pm10=highest_pm10, highest_pm10_timestamp=highest_pm10_timestamp
    )


@app.route("/toggle_user_status", methods=["POST"])
def toggle_user_status():
    if "user_type" not in session or session["user_type"] != "admin":
        return "Unauthorized", 403

    email = request.form["email"]
    db = get_db()

    user = db.users.find_one({"email": email})
    if user:
        db.users.update_one({"email": email}, {"$set": {"is_active": not user["is_active"]}})

    return redirect("/dashboard")


@app.route("/change_user_role", methods=["POST"])
def change_user_role():
    if "user_type" not in session or session["user_type"] != "admin":
        return "Unauthorized", 403

    email = request.form["email"]
    new_role = request.form["new_role"]
    db = get_db()

    db.users.update_one({"email": email}, {"$set": {"user_type": new_role}})

    return redirect("/admin")

@app.route("/blockchain")
def blockchain_page():
    blockchain_data = blockchain.get_chain()
    return render_template("blockchain.html", blockchain_data=blockchain_data)

@app.route("/add_block", methods=["POST"])
def add_block():
    data = request.json  # Expecting {"PM2.5": 120, "PM10": 200}
    blockchain.add_block(data)
    return jsonify({"message": "Block added successfully!", "data": data}), 201


### User Registration API ###
@app.route("/register", methods=["GET", "POST"])
def api_register():
    if request.method == "POST":
        if request.content_type == "application/json":
            data = request.get_json()
            is_api_request = True  # API request
        else:
            data = request.form  # Accept form data as well
            is_api_request = False  # Web form request

        if not data or "email" not in data or "password" not in data or "user_type" not in data:
            return jsonify({"error": "Missing required fields"}), 400

        success, message = register_user_api(data["email"], data["password"], data["user_type"])

        if success:
            if is_api_request:
                return jsonify({"message": message}), 201  # API response
            else:
                flash("User registered successfully. Please wait for admin approval.", "success")
                return redirect("/")  # Redirect to index after registration

        else:
            if is_api_request:
                return jsonify({"error": message}), 409  # API error response
            else:
                flash(message, "error")
                return redirect("/register")  # Redirect back to registration page on failure

    return render_template("register.html")  # Render form if it's a GET request


### User Login API ###
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    if not data or "email" not in data or "password" not in data:
        return jsonify({"error": "Missing email or password"}), 400

    user = get_db().users.find_one({"email": data["email"]})
    if not user:
        return jsonify({"error": "User not found"}), 404
    if not user["is_active"]:
        return jsonify({"error": "Account not approved by admin"}), 403
    if not check_password_hash(user["password"], data["password"]):
        return jsonify({"error": "Invalid password"}), 401

    token = jwt.encode({"email": user["email"], "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)},
                       app.config["SECRET_KEY"], algorithm="HS256")

    return jsonify({"token": token}), 200


### Secure User Profile API ###
@app.route('/api/user', methods=['GET'])
@token_required
def get_user(current_user):
    return jsonify({
        "email": current_user["email"],
        "user_type": current_user["user_type"],
        "is_active": current_user["is_active"]
    })


### Admin API: Activate User ###
@app.route("/api/admin/activate_user", methods=["POST"])
@token_required
def activate_user(current_user):
    if current_user["user_type"] != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    email = data.get("email")
    db = get_db()

    if db.users.find_one({"email": email}):
        db.users.update_one({"email": email}, {"$set": {"is_active": True}})
        return jsonify({"message": f"User {email} activated."}), 200

    return jsonify({"error": "User not found"}), 404


@app.route("/admin")
def admin_panel():
    if "user_type" not in session or session["user_type"] != "admin":
        flash("Unauthorized access!", "error")
        return redirect("/login")  # Redirect unauthorized users to login

    db = get_db()
    users = list(db.users.find({}, {"_id": 0, "password": 0}))  # Exclude password
    pollution_data = list(db.pollution_data.find({}, {"_id": 0}).sort("timestamp", -1).limit(10))
    pm10_threshold = 150

    return render_template("admin.html", users=users,data=pollution_data)

### API Logout ###
@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"message": "Logout successful. Delete your token on client-side."}), 200

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        db = get_db()
        users_collection = db["users"]

        user = users_collection.find_one({"email": email})

        if user and check_password_hash(user["password"], password):
            if not user["is_active"]:
                flash("Your account is not active. Please contact the admin.", "error")
                return redirect("/login")

            session["user_type"] = user["user_type"]
            return redirect("/dashboard")

        flash("Invalid email or password.", "error")
        return redirect("/login")

    return render_template("login.html")

@app.route("/index")
def index_redirect():
    return redirect("/")

#BOT API
@app.route("/api/set_bot_sleep", methods=["POST"])
def set_bot_sleep():
    """Allows the admin to update the bot's sleep interval."""
    if "user_type" not in session or session["user_type"] != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    new_sleep_time = data.get("sleep_time")

    if not isinstance(new_sleep_time, int) or new_sleep_time <= 0:
        return jsonify({"error": "Invalid sleep time"}), 400

    db = get_db()
    db.config.update_one({"name": "bot_settings"}, {"$set": {"sleep_time": new_sleep_time}}, upsert=True)

    return jsonify({"message": f"Bot sleep time updated to {new_sleep_time} seconds"}), 200

@app.route("/api/get_bot_sleep", methods=["GET"])
def get_bot_sleep():
    """Returns the current bot sleep time."""
    db = get_db()
    config = db.config.find_one({"name": "bot_settings"}, {"_id": 0, "sleep_time": 1})
    return jsonify({"sleep_time": config["sleep_time"] if config else BOT_SLEEP_TIME})



@app.route("/admin_activate_actuator", methods=["POST"])
def admin_activate_actuator():
    """Allows an admin to manually activate the actuator if PM10 is in amber range."""
    if "user_type" not in session or session["user_type"] != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    pm10_value = float(request.form.get("pm10_value", 0))
    timestamp = request.form.get("timestamp", "")

    if 120 <= pm10_value <= 150:
        try:
            response = requests.post("http://127.0.0.1:5002/actuator", json={"PM10": pm10_value, "manual": True})
            return redirect("/admin")  # Redirect to Admin Panel after activation
        except requests.exceptions.RequestException as e:
            return f"Error triggering actuator: {e}", 500
    else:
        return jsonify({"error": "PM10 value is not in the amber range (80-100)."}), 400


### Run Flask App ###
if __name__ == "__main__":
    app.run(debug=True)
