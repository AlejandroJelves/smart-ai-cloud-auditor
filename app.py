from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

dummy_data = [
    {"provider": "gcp", "service": "Compute Engine", "cost": 120.50},
    {"provider": "aws", "service": "EC2", "cost": 98.75},
    {"provider": "azure", "service": "Virtual Machines", "cost": 45.30}
]

@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/chat")
def chat():
    return render_template("chat.html")

@app.route("/api/costs")
def costs():
    return jsonify(dummy_data)

# Temporary fake agent
@app.route("/api/agent", methods=["POST"])
def agent():
    question = request.json.get("question", "")
    return jsonify({"answer": f"🤖 (dummy) I received your question: '{question}'"})

if __name__ == "__main__":
    app.run(debug=True, port=5001)
