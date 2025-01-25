from pymongo import MongoClient

def get_db():
    client = MongoClient("mongodb://localhost:27017/")
    db = client["air_pollution"]
    return db

def store_sensor_data(data):
    db = get_db()
    db.pollution_data.insert_one(data)