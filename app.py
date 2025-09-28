from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
from services import gcp_connector, gcp_live, gemini
import random


app = Flask(__name__)

# ------------------ pages ------------------
@app.route("/")
def dashboard():
    return render_template("dashboard.html")

# ------------------ summaries & costs ------------------
@app.route("/api/summary", methods=["POST"])
def summary():
    body = request.json or {}
    data = body.get("data", [])
    try:
        text = gemini.summarize_costs(data)
        return jsonify({"summary": text})
    except Exception as e:
        return jsonify({"summary": f"⚠️ Error generating summary: {str(e)}"})

@app.route("/api/costs")
def costs():
    range_days = request.args.get("range")
    provider = request.args.get("provider")

    # ---- Tiles / Pie ----
    if not range_days:
        try:
            gcp_real = gcp_connector.get_mtd_costs_by_project_service()
            gcp_total = sum([r["mtd_cost"] for r in gcp_real])
        except Exception:
            gcp_total = 0.0

        tiles = [
            {"provider": "gcp",   "service": "Compute Engine", "cost": gcp_total},
            {"provider": "aws",   "service": "EC2",            "cost": 98.75},     # demo values
            {"provider": "azure", "service": "VMs",            "cost": 45.30}
        ]
        return jsonify(tiles)

    # ---- Charts (demo values grouped) ----
    range_days = int(range_days)
    today = datetime.today()
    dates = [today - timedelta(days=i) for i in range(range_days - 1, -1, -1)]

    gcp_vals   = [random.randint(20, 90) for _ in dates]
    aws_vals   = [random.randint(15, 80) for _ in dates]
    azure_vals = [random.randint(10, 70) for _ in dates]

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

    if provider:
        if provider == "gcp":
            try:
                gcp_trend = gcp_connector.get_daily_cost_trend(days=range_days)
                labels = [r["day"] for r in gcp_trend]
                values = [r["daily_cost"] for r in gcp_trend]
            except Exception:
                labels, values = grouped_labels, gcp_grouped
            color, name = "#4285F4", "Google Cloud"
        elif provider == "aws":
            labels, values, color, name = grouped_labels, aws_grouped, "#FF9900", "AWS"
        elif provider == "azure":
            labels, values, color, name = grouped_labels, azure_grouped, "#0078D4", "Azure"
        else:
            return jsonify({"error": "Invalid provider"}), 400

        total = sum(values)
        avg = total / len(values) if values else 0
        budget = 2000
        idle = random.randint(0, 5)

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

    return jsonify({
        "labels": grouped_labels,
        "datasets": [
            {"label": "Provider A", "data": gcp_grouped,   "borderColor": "#4285F4", "fill": False},
            {"label": "Provider B", "data": aws_grouped,   "borderColor": "#FF9900", "fill": False},
            {"label": "Provider C", "data": azure_grouped, "borderColor": "#0078D4", "fill": False}
        ]
    })

# ------------------ LIVE METRICS (VM) ------------------
@app.get("/api/tiles")
def api_tiles():
    """Top tiles: cpu %, traffic in/out, disk r/w, error logs."""
    return jsonify(gcp_live.tiles_summary())

@app.get("/api/traffic")
def api_traffic():
    """
    VM traffic time-series (Mbps) for last 30 min.
    """
    data = gcp_live.traffic_timeseries(minutes=30, step_seconds=60)
    return jsonify({
        "labels": data["ts"],
        "datasets": [
            {"id": "gcp-in",  "provider": "gcp", "label": "Ingress (Mbps)", "data": data["mbps_in"]},
            {"id": "gcp-out", "provider": "gcp", "label": "Egress (Mbps)",  "data": data["mbps_out"]}
        ]
    })

@app.get("/api/cpu")
def api_cpu():
    """
    VM CPU % time-series for last 30 min.
    """
    data = gcp_live.cpu_timeseries(minutes=30, step_seconds=60)
    return jsonify({
        "labels": data["ts"],
        "datasets": [
            {"id": "gcp-cpu", "provider": "gcp", "label": "CPU %", "data": data["cpu_percent"]}
        ]
    })

if __name__ == "__main__":
    app.run(debug=True, port=5001)
