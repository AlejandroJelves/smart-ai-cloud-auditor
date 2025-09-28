from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
from services import gcp_connector, gcp_live, gemini
from agent_app import create_cloud_audit_agent

app = Flask(__name__)
cloud_audit_agent = create_cloud_audit_agent()

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

        # Use same dummy values as agent_app
        aws_total = 98.75
        azure_total = 45.30

        tiles = [
            {"provider": "gcp",   "service": "Compute Engine", "cost": gcp_total},
            {"provider": "aws",   "service": "EC2",            "cost": aws_total},
            {"provider": "azure", "service": "VMs",            "cost": azure_total}
        ]
        return jsonify(tiles)

    # ---- Charts (dummy static trend instead of random) ----
    range_days = int(range_days)
    today = datetime.today()
    dates = [today - timedelta(days=i) for i in range(range_days - 1, -1, -1)]
    labels = [d.strftime("%Y-%m-%d") for d in dates]

    # Live GCP daily trend
    try:
        gcp_trend = gcp_connector.get_daily_cost_trend(days=range_days)
        gcp_labels = [r["day"] for r in gcp_trend]
        gcp_values = [r["daily_cost"] for r in gcp_trend]
    except Exception:
        gcp_labels, gcp_values = labels, [50.0 for _ in labels]

    # Dummy AWS & Azure daily trend (flat values)
    aws_values = [50.0 for _ in labels]
    azure_values = [30.0 for _ in labels]

    if provider:
        if provider == "gcp":
            labels, values, color, name = gcp_labels, gcp_values, "#4285F4", "Google Cloud"
        elif provider == "aws":
            labels, values, color, name = labels, aws_values, "#FF9900", "AWS"
        elif provider == "azure":
            labels, values, color, name = labels, azure_values, "#0078D4", "Azure"
        else:
            return jsonify({"error": "Invalid provider"}), 400

        total = sum(values)
        avg = total / len(values) if values else 0
        budget = 2000
        idle = 2  # fixed dummy

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
        "labels": labels,
        "datasets": [
            {"label": "Google Cloud", "data": gcp_values,   "borderColor": "#4285F4", "fill": False},
            {"label": "AWS",          "data": aws_values,   "borderColor": "#FF9900", "fill": False},
            {"label": "Azure",        "data": azure_values, "borderColor": "#0078D4", "fill": False}
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

@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.json or {}
    q = (body.get("query") or "").strip()
    if not q:
        return jsonify({"error": "Missing query"}), 400
    try:
        out = cloud_audit_agent.chat(q)
        return jsonify({"response": out["text"], "traces": out["calls"]})
    except Exception as e:
        return jsonify({"error": f"Chat error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5001)
