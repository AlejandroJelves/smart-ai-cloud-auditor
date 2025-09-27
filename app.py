from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
from services import gcp_connector
from services import gemini

import random


app = Flask(__name__)

# Tile & pie summary data
dummy_data = [
    {"provider": "gcp", "service": "Compute Engine", "cost": 120.50},
    {"provider": "aws", "service": "EC2", "cost": 98.75},
    {"provider": "azure", "service": "Virtual Machines", "cost": 45.30}
]

@app.route("/api/gcp/mtd")
def gcp_mtd():
    try:
        data = gcp_connector.get_mtd_costs_by_project_service()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)})
    
@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/api/summary", methods=["POST"])
def summary():
    body = request.json
    data = body.get("data", [])
    try:
        text = gemini.summarize_costs(data)  # 🔹 ask Gemini to generate a summary
        return jsonify({"summary": text})
    except Exception as e:
        return jsonify({"summary": f"⚠️ Error generating summary: {str(e)}"})
    
@app.route("/chat")
def chat():
    return render_template("chat.html")

@app.route("/api/costs")
def costs():
    range_days = request.args.get("range")
    provider = request.args.get("provider")

    # ---- Tiles / Pie (no range selected) ----
    if not range_days:
        try:
            # 🔹 Pull real GCP cost from connector
            gcp_real = gcp_connector.get_mtd_costs_by_project_service()
            gcp_total = sum([r["mtd_cost"] for r in gcp_real])
        except Exception:
            # 🔹 If connector fails, fall back to dummy
            gcp_total = 120.50  

        # 🔹 Build tile data: GCP real, AWS & Azure dummy
        dummy_data = [
            {"provider": "gcp", "service": "Compute Engine", "cost": gcp_total},
            {"provider": "aws", "service": "EC2", "cost": 98.75},
            {"provider": "azure", "service": "Virtual Machines", "cost": 45.30}
        ]
        return jsonify(dummy_data)

    # ---- Charts (still dummy values, grouped) ----
    range_days = int(range_days)
    today = datetime.today()
    dates = [today - timedelta(days=i) for i in range(range_days-1, -1, -1)]

    # 🔹 FIX: Generate dummy values before grouping
    gcp_vals   = [random.randint(40,120) for _ in dates]
    aws_vals   = [random.randint(30,100) for _ in dates]
    azure_vals = [random.randint(20,90)  for _ in dates]

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

    # ✅ Provider-specific stats
    if provider:
        if provider == "gcp":
            try:
                # 🔹 Real daily cost trend from connector
                gcp_trend = gcp_connector.get_daily_cost_trend(days=range_days)
                labels = [r["day"] for r in gcp_trend]
                values = [r["daily_cost"] for r in gcp_trend]
            except Exception:
                # 🔹 fallback to dummy if connector fails
                labels = grouped_labels
                values = gcp_grouped
            color, name = "#4285F4", "Google Cloud"

        elif provider == "aws":
            labels, values, color, name = grouped_labels, aws_grouped, "#FF9900", "AWS"
        elif provider == "azure":
            labels, values, color, name = grouped_labels, azure_grouped, "#0078D4", "Azure"
        else:
            return jsonify({"error": "Invalid provider"}), 400

        total = sum(values)
        avg = total / len(values) if values else 0
        budget = 2000  # dummy budget
        idle = random.randint(0, 5)  # dummy idle resources

        return jsonify({
            "labels": labels,
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
