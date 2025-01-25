from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/actuator', methods=['POST'])
def activate_actuator():
    data = request.get_json()
    return jsonify({"message": "Actuator activated to reduce pollution", "status": "success", "details": data})

if __name__ == "__main__":
    app.run(port=5002)
