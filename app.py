from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
import random

app = Flask(__name__)

# Tile & pie summary data
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
    range_days = request.args.get("range")
    provider = request.args.get("provider")

    # Default → summary tiles/pie (dummy)
    if not range_days:
        return jsonify(dummy_data)

    range_days = int(range_days)
    today = datetime.today()

    # Generate random daily values
    dates = [today - timedelta(days=i) for i in range(range_days-1, -1, -1)]
    gcp_vals = [random.randint(40,120) for _ in dates]
    aws_vals = [random.randint(30,100) for _ in dates]
    azure_vals = [random.randint(20,90) for _ in dates]

    # Grouping step (keeps charts clean)
    if range_days <= 30:
        step = 1
    elif range_days <= 90:
        step = 7
    elif range_days <= 180:
        step = 15
    else:
        step = 30

    grouped_labels, gcp_grouped, aws_grouped, azure_grouped = [], [], [], []
    for i in range(0, len(dates), step):
        chunk_dates = dates[i:i+step]
        if not chunk_dates: 
            continue
        grouped_labels.append(chunk_dates[0].strftime("%Y-%m-%d"))
        gcp_grouped.append(sum(gcp_vals[i:i+step]) // len(chunk_dates))
        aws_grouped.append(sum(aws_vals[i:i+step]) // len(chunk_dates))
        azure_grouped.append(sum(azure_vals[i:i+step]) // len(chunk_dates))

    # ✅ Provider-specific dummy stats
    if provider:
        if provider == "gcp":
            values, color, name = gcp_grouped, "#4285F4", "Provider A"
        elif provider == "aws":
            values, color, name = aws_grouped, "#FF9900", "Provider B"
        elif provider == "azure":
            values, color, name = azure_grouped, "#0078D4", "Provider C"
        else:
            return jsonify({"error": "Invalid provider"}), 400

        total = sum(values)
        avg = total / len(values) if values else 0
        budget = 2000  # dummy budget
        idle = random.randint(0, 5)  # dummy idle resources

        return jsonify({
            "labels": grouped_labels,
            "datasets": [
                {"label": f"{name} Spend", "data": values, "borderColor": color, "fill": False}
            ],
            "summary": {
                "total": total,
                "avg": avg,
                "budgetStatus": "⚠️ Over Budget" if total > budget else "✅ Under Budget",
                "idle": idle
            }
        })

    # ✅ Overview: return all providers together
    return jsonify({
        "labels": grouped_labels,
        "datasets": [
            {"label": "Provider A", "data": gcp_grouped, "borderColor": "#4285F4", "fill": False},
            {"label": "Provider B", "data": aws_grouped, "borderColor": "#FF9900", "fill": False},
            {"label": "Provider C", "data": azure_grouped, "borderColor": "#0078D4", "fill": False}
        ]
    })

# Fake chatbot agent
@app.route("/api/agent", methods=["POST"])
def agent():
    question = request.json.get("question", "")
    return jsonify({"answer": f"🤖 (dummy) I received your question: '{question}'"})

if __name__ == "__main__":
    app.run(debug=True, port=5001)
