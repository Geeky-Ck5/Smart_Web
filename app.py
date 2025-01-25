from flask import Flask, render_template, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from db.mongodb.py import store_sensor_data
from blockchain.blockchain import Blockchain

app = Flask(__name__)
blockchain = Blockchain()

air_pollution_data = []  # To hold real-time data

def fetch_sensor_data():
    global air_pollution_data
    response = requests.get("http://127.0.0.1:5001/sensor")
    data = response.json()
    air_pollution_data.append(data)
    store_sensor_data(data)
    if data["PM2.5"] > 100:  # Threshold
        activate_actuator(data)

def activate_actuator(data):
    requests.post("http://127.0.0.1:5002/actuator", json={"PM2.5": data["PM2.5"]})

scheduler = BackgroundScheduler()
scheduler.add_job(fetch_sensor_data, "interval", minutes=5)
scheduler.start()

@app.route('/')
def index():
    return render_template("index.html", data=air_pollution_data)

@app.route('/blockchain', methods=['GET'])
def get_blockchain():
    return jsonify(blockchain.get_chain())

if __name__ == "__main__":
    app.run(debug=True)
