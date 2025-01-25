from flask import Flask, jsonify
import random

app = Flask(__name__)

@app.route('/sensor', methods=['GET'])
def get_sensor_data():
    data = {
        "PM2.5": round(random.uniform(10, 150), 2),
        "PM10": round(random.uniform(10, 200), 2),
        "timestamp": "2025-01-25T12:00:00Z"
    }
    return jsonify(data)

if __name__ == "__main__":
    app.run(port=5001)  # Run on a separate port
