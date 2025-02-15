import requests
import time
from datetime import datetime

SENSOR_API_URL = "http://127.0.0.1:5001/sensor"
ACTUATOR_API_URL = "http://127.0.0.1:5002/actuator"
CONFIG_API_URL = "http://127.0.0.1:5000/api/get_bot_sleep"

PM25_THRESHOLD = 100
PM10_THRESHOLD = 150

def log_message(message):
    """Helper function to print messages with a timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def get_bot_sleep_time():
    """Fetches the latest bot sleep time from the API."""
    try:
        response = requests.get(CONFIG_API_URL)
        if response.status_code == 200:
            return response.json().get("sleep_time", 5)  # Default to 5 seconds if not found
    except requests.exceptions.RequestException:
        log_message("⚠️ Failed to fetch bot sleep time, using default (5s)")
    return 5  # Default fallback sleep time

def fetch_and_check_sensor_data():
    """Fetches air pollution data and triggers actuator if needed."""
    response = requests.get(SENSOR_API_URL)
    if response.status_code == 200:
        data = response.json()
        pm25 = data.get("PM2.5", 0)
        pm10 = data.get("PM10", 0)

        print(f"PM2.5: {pm25}, PM10: {pm10}")

        if pm25 > PM25_THRESHOLD or pm10 > PM10_THRESHOLD:
            trigger_actuator(pm25, pm10)

def trigger_actuator(pm25, pm10):
    """Triggers the actuator when pollution is above threshold."""
    log_message(f"⚠️ Triggering Actuator: PM2.5={pm25}, PM10={pm10}")
    response = requests.post(ACTUATOR_API_URL, json={"PM2.5": pm25, "PM10": pm10})
    if response.status_code == 200:
        log_message("✅ Actuator Triggered Successfully")
    else:
        log_message("❌ Failed to Trigger Actuator")

while True:
    sleep_time = get_bot_sleep_time()
    fetch_and_check_sensor_data()
    log_message(f"⏳ Bot sleeping for {sleep_time} seconds...")
    time.sleep(sleep_time)
