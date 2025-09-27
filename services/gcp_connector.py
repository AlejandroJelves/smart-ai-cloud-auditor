# services/gcp_connector.py
import os
import datetime as dt
from typing import List, Dict, Any
from google.cloud import bigquery, monitoring_v3, firestore, recommender_v1
from dotenv import load_dotenv

# --- ENV ---
load_dotenv()  # ✅ load from .env automatically

# --- ENV ---
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")  # <-- correct name
BILLING_DATASET = os.getenv("BILLING_DATASET", "billing_export")
USE_FIRESTORE_CACHE = os.getenv("USE_FIRESTORE_CACHE", "true").lower() in ("1", "true", "yes")

# --- CLIENTS ---
_bq = bigquery.Client(project=GCP_PROJECT_ID)
_mon = monitoring_v3.MetricServiceClient()
_fs  = firestore.Client(project=GCP_PROJECT_ID)
_rec = recommender_v1.RecommenderClient()

# --- HELPERS ---
def _now() -> dt.datetime:
    # timezone-aware UTC
    return dt.datetime.now(dt.timezone.utc)

def _iso(t: dt.datetime) -> str:
    return t.isoformat()

# =========================
# COSTS (BigQuery export)
# =========================
def get_mtd_costs_by_project_service() -> List[Dict[str, Any]]:
    sql = f"""
    SELECT
      project.name AS project,
      service.description AS service,
      ROUND(SUM(cost), 2) AS mtd_cost
    FROM `{BILLING_DATASET}.gcp_billing_export_v1_*`
    WHERE usage_start_time >= TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), MONTH)
    GROUP BY 1,2
    ORDER BY mtd_cost DESC
    """
    return [dict(r) for r in _bq.query(sql).result()]

def get_daily_cost_trend(days: int = 30) -> List[Dict[str, Any]]:
    sql = f"""
    SELECT
      DATE(usage_start_time) AS day,
      ROUND(SUM(cost), 2) AS daily_cost
    FROM `{BILLING_DATASET}.gcp_billing_export_v1_*`
    WHERE usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY day
    ORDER BY day
    """
    return [{"day": str(r["day"]), "daily_cost": r["daily_cost"]} for r in _bq.query(sql).result()]

def get_top_services_last_7d(limit: int = 10) -> List[Dict[str, Any]]:
    sql = f"""
    SELECT
      service.description AS service,
      ROUND(SUM(cost), 2) AS cost_7d
    FROM `{BILLING_DATASET}.gcp_billing_export_v1_*`
    WHERE usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    GROUP BY service
    ORDER BY cost_7d DESC
    LIMIT {limit}
    """
    return [dict(r) for r in _bq.query(sql).result()]

# =========================
# LIVE (Monitoring / Firestore cache)
# =========================
def _cpu_avg_last_5m() -> float:
    name = f"projects/{GCP_PROJECT_ID}"
    interval = monitoring_v3.TimeInterval(end_time=_now(), start_time=_now() - dt.timedelta(minutes=5))
    req = {
        "name": name,
        "filter": 'metric.type="compute.googleapis.com/instance/cpu/utilization"',
        "interval": interval,
        "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        "aggregation": {
            "alignment_period": {"seconds": 300},
            "per_series_aligner": monitoring_v3.Aggregation.Aligner.ALIGN_MEAN,
            "cross_series_reducer": monitoring_v3.Aggregation.Reducer.REDUCE_MEAN,
        },
    }
    vals = [p.value.double_value for ts in _mon.list_time_series(request=req) for p in ts.points]
    return round(100.0 * (sum(vals) / len(vals)), 1) if vals else 0.0

def _egress_mbps_last_5m() -> float:
    name = f"projects/{GCP_PROJECT_ID}"
    interval = monitoring_v3.TimeInterval(end_time=_now(), start_time=_now() - dt.timedelta(minutes=5))
    req = {
        "name": name,
        "filter": 'metric.type="compute.googleapis.com/instance/network/sent_bytes_count"',
        "interval": interval,
        "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        "aggregation": {
            "alignment_period": {"seconds": 300},
            "per_series_aligner": monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
            "cross_series_reducer": monitoring_v3.Aggregation.Reducer.REDUCE_SUM,
        },
    }
    bps = sum(p.value.double_value for ts in _mon.list_time_series(request=req) for p in ts.points)  # bytes/sec
    return round((bps * 8.0) / 1_000_000.0, 1)  # Mbps

def get_live_summary() -> Dict[str, Any]:
    if USE_FIRESTORE_CACHE:
        snap = _fs.collection("realtime").document("summary").get()
        if snap.exists:
            d = snap.to_dict() or {}
            return {
                "updated_at": d.get("updated_at"),
                "overall_cpu_avg": d.get("overall_cpu_avg", 0.0),
                "overall_network_mbps": d.get("overall_network_mbps", 0.0),
                "active_instances": d.get("active_instances", 0),
                "unlabeled_assets_pct": d.get("unlabeled_assets_pct", 0.0),
            }
    # live fallback
    return {
        "updated_at": _iso(_now()),
        "overall_cpu_avg": _cpu_avg_last_5m(),
        "overall_network_mbps": _egress_mbps_last_5m(),
        "active_instances": None,
        "unlabeled_assets_pct": None,
    }

# =========================
# (Optional) RECOMMENDER
# =========================
_RECS = [
    "google.compute.instance.MachineTypeRecommender",
    "google.compute.instance.IdleResourceRecommender",
    "google.compute.disk.IdleResourceRecommender",
]

def get_recommendations(limit: int = 10) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for rid in _RECS:
        parent = f"projects/{GCP_PROJECT_ID}/locations/global/recommenders/{rid}"
        try:
            for r in _rec.list_recommendations(parent=parent):
                est = 0.0
                if r.primary_impact and r.primary_impact.cost_projection:
                    try:
                        est = float(r.primary_impact.cost_projection.cost)
                    except Exception:
                        est = 0.0
                out.append({
                    "name": r.name,
                    "description": r.description,
                    "recommender_id": rid,
                    "resource": (r.content.overview.get("resourceName") if r.content and r.content.overview else None),
                    "est_savings_monthly": round(est, 2),
                })
        except Exception:
            continue
    out.sort(key=lambda x: x.get("est_savings_monthly", 0.0), reverse=True)
    return out[:limit]
