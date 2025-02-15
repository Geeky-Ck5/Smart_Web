from pymongo import MongoClient

MONGO_URI = "mongodb+srv://mytkavish:mytkavish@cluster0.z8s2k.mongodb.net/air_pollution_db"
client = MongoClient(MONGO_URI)
db = client["air_pollution_db"]

users = db["users"].find()
for user in users:
    print(user)