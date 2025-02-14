import hashlib
import time
from db.mongodb import get_db

class Block:
    def __init__(self, index, timestamp, data, previous_hash,hash_value=None):
        self.index = index
        self.timestamp = timestamp
        self.data = data
        self.previous_hash = previous_hash
        self.hash = hash_value if hash_value else self.calculate_hash()

    def calculate_hash(self):
        data_string = f"{self.index}{self.timestamp}{self.data}{self.previous_hash}"
        return hashlib.sha256(data_string.encode()).hexdigest()

    def to_dict(self):
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "data": self.data,
            "previous_hash": self.previous_hash,
            "hash": self.hash
        }


class Blockchain:
    def __init__(self):
        self.db = get_db()
        self.chain = self.load_chain_from_db()  # Load blockchain from MongoDB

    def create_genesis_block(self):
        genesis_block = Block(0, time.time(), {"PM2.5": 0, "PM10": 0, "message": "Genesis Block"}, "0")
        self.db.blockchain.insert_one(genesis_block.to_dict())  # Store in MongoDB
        return genesis_block

    def load_chain_from_db(self):
        blockchain_data = list(self.db.blockchain.find({}, {"_id": 0}))  # Fetch blockchain from DB

        # Fix: Ensure we only pass expected fields
        chain = []
        for block in blockchain_data:
            chain.append(Block(
                index=block["index"],
                timestamp=float(block["timestamp"]),  # Ensure timestamp is a float
                data=block["data"],
                previous_hash=block["previous_hash"],
                hash_value=block["hash"]
            ))
        return chain if chain else [self.create_genesis_block()]

    def add_block(self, data):
        previous_block = self.chain[-1]
        new_block = Block(len(self.chain), time.time(), data, previous_block.hash)
        self.chain.append(new_block)

        # Save block to MongoDB
        self.db.blockchain.insert_one(new_block.to_dict())

    def get_chain(self):
        return [block.to_dict() for block in self.chain]