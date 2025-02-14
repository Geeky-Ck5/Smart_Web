from flask import Flask, render_template, jsonify, request, redirect, session
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from werkzeug.security import generate_password_hash, check_password_hash

from db.mongodb import store_sensor_data, register_user, authenticate_user, create_users_collection, get_db
from blockchain.blockchain import Blockchain
import datetime

app = Flask(__name__)
app.secret_key = "supersecretkey"

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
scheduler.add_job(fetch_sensor_data, "interval", seconds=30)
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
    pollution_data = list(db.pollution_data.find({}, {"_id": 0}))

    # Fetch blockchain summary
    blockchain_data = blockchain.get_chain()

    return render_template("dashboard.html", data=pollution_data,blockchain_data=blockchain_data, user_role=user_role)


@app.route("/activate_actuator", methods=["POST"])
def activate_actuator():
    if "user_type" in session and session["user_type"] in ["admin", "home_user"]:
        requests.post("http://127.0.0.1:5002/actuator")
        return redirect("/dashboard")
    return "Unauthorized", 403


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

### User Logout ###
@app.route("/logout")
def logout():
    session.pop("user_type", None)
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)
