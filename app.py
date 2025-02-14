from flask import Flask, render_template, jsonify, request, redirect, session
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from werkzeug.security import generate_password_hash, check_password_hash

from db.mongodb import store_sensor_data, register_user, authenticate_user, create_users_collection, get_db
from blockchain.blockchain import Blockchain
import datetime
import os
app = Flask(__name__)
app.secret_key = os.urandom(24)  # Generate a new secret key every restart (forces session reset)
app.config['SESSION_PERMANENT'] = False  # Ensure sessions expire when the app closes

blockchain = Blockchain()
air_pollution_data = []  # Stores real-time pollution data

# Ensure users collection exists
create_users_collection()


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

    # Check threshold and trigger actuator if needed
    if data["PM2.5"] > 100:
        activate_actuator()


### Activate Actuator API ###
def activate_actuator():
    requests.post("http://127.0.0.1:5002/actuator", json={"PM2.5"})


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
scheduler.add_job(fetch_sensor_data, "interval", seconds=5)
scheduler.add_job(store_weekly_summary, "interval", weeks=1)
scheduler.start()


### Flask Routes ###
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

    # Fetch the latest 10 records (Sorted by timestamp descending)
    pollution_data = list(db.pollution_data.find({}, {"_id": 0}).sort("timestamp", -1).limit(10))

    # Get last 10 blockchain records
    blockchain_data = blockchain.get_chain()[-10:]

    # Get total counts
    total_pollution = db.pollution_data.count_documents({})
    total_blocks = len(blockchain_data)

    # Fix: Ensure we are counting PM2.5 values above threshold properly
    pm25_threshold = 100  # PM2.5 threshold value
    pm10_threshold = 150  # PM10 threshold value

    pm25_threshold_count = db.pollution_data.count_documents({"PM2.5": {"$gt": pm25_threshold}})
    pm10_threshold_count = db.pollution_data.count_documents({"PM10": {"$gt": pm10_threshold}})
    actuator_count = pm25_threshold_count + pm10_threshold_count

    # Fix: Fetch Highest PM2.5 & PM10 Values
    highest_pm25_doc = db.pollution_data.find_one({"PM2.5": {"$exists": True, "$gt": 0}}, sort=[("PM2.5", -1)])
    highest_pm10_doc = db.pollution_data.find_one({"PM10": {"$exists": True, "$gt": 0}}, sort=[("PM10", -1)])

    highest_pm25 = highest_pm25_doc["PM2.5"] if highest_pm25_doc else "No Data"
    highest_pm25_timestamp = highest_pm25_doc["timestamp"] if highest_pm25_doc else "No Data"

    highest_pm10 = highest_pm10_doc["PM10"] if highest_pm10_doc else "No Data"
    highest_pm10_timestamp = highest_pm10_doc["timestamp"] if highest_pm10_doc else "No Data"

    return render_template("dashboard.html",
                           data=pollution_data, blockchain_data=blockchain_data,
                           total_pollution=total_pollution, total_blocks=total_blocks,
                           pm25_threshold_count=pm25_threshold_count, pm10_threshold_count=pm10_threshold_count,
                           actuator_count=actuator_count,
                           highest_pm25=highest_pm25, highest_pm25_timestamp=highest_pm25_timestamp,
                           highest_pm10=highest_pm10, highest_pm10_timestamp=highest_pm10_timestamp)


@app.route("/activate_actuator", methods=["POST"])
def activate_actuator():
    """Triggers the actuator when pollution levels exceed the threshold."""
    try:
        response = requests.post("http://127.0.0.1:5002/actuator")
        print(f"Actuator triggered: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error triggering actuator: {e}")


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

    return redirect("/dashboard")

@app.route("/blockchain")
def blockchain_page():
    blockchain_data = blockchain.get_chain()
    return render_template("blockchain.html", blockchain_data=blockchain_data)

@app.route("/add_block", methods=["POST"])
def add_block():
    data = request.json  # Expecting {"PM2.5": 120, "PM10": 200}
    blockchain.add_block(data)
    return jsonify({"message": "Block added successfully!", "data": data}), 201


@app.route("/admin")
def admin_panel():
    if "user_type" not in session or session["user_type"] != "admin":
        return "Unauthorized", 403

    db = get_db()
    users = list(db.users.find({}, {"_id": 0, "password": 0}))

    return render_template("admin.html", users=users)

@app.route("/index")
def index_redirect():
    return redirect("/")

@app.route("/reports")
def reports():
    db = get_db()

    # Default: Fetch all pollution data
    pollution_data = list(db.pollution_data.find({}, {"_id": 0}))

    # Get date filters from request
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    if start_date and end_date:
        # Convert string dates to datetime format for MongoDB query
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        # Adjust MongoDB query to match stored ISO format
        pollution_data = list(db.pollution_data.find({
            "timestamp": {
                "$gte": start_dt.strftime("%Y-%m-%dT00:00:00Z"),
                "$lte": end_dt.strftime("%Y-%m-%dT23:59:59Z")
            }
        }, {"_id": 0}))

    # Prepare data for Chart.js
    timestamps = [entry["timestamp"] for entry in pollution_data]
    pm25_values = [entry["PM2.5"] for entry in pollution_data]
    pm10_values = [entry["PM10"] for entry in pollution_data]

    return render_template("report.html", data=pollution_data,
                           timestamps=timestamps, pm25_values=pm25_values, pm10_values=pm10_values)


### User Registration ###
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user_type = request.form["user_type"]

        # Hash the password before storing
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        db = get_db()
        users_collection = db["users"]

        # Ensure user is stored as inactive until email activation (for future enhancement)
        user_data = {"email": email, "password": hashed_password, "user_type": user_type, "is_active": False}

        try:
            users_collection.insert_one(user_data)
            return "<h3>Account registered! Please wait for admin approval.</h3>"
        except Exception as e:
            return f"<h3>Error: {e}</h3>"

    return render_template("register.html")
### User Login ###
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
                return "<h3>Your account is not active. Please contact the admin.</h3>"

            session["user_type"] = user["user_type"]
            return redirect("/dashboard") if user["user_type"] == "admin" else redirect("/")

        return "<h3>Invalid email or password</h3>"

    return render_template("login.html")

@app.before_request
def clear_session_on_restart():
    if "user_type" in session:
        session.pop("user_type", None)  # Clear the session on restart

### User Logout ###
@app.route("/logout")
def logout():
    session.pop("user_type", None)
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)
