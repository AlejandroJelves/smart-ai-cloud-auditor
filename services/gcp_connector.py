# services/gcp_connector.py
import os
import datetime as dt
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
load_dotenv()  # must be before creating any google clients

# ---------------- ENV ----------------
GCP_PROJECT_ID       = os.getenv("GCP_PROJECT_ID", "").strip()
GOOGLE_KEY_PATH      = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")  # absolute path to JSON
BILLING_DATASET      = os.getenv("BILLING_DATASET", "billing_export").strip()
BQ_BILLING_TABLE     = os.getenv("BQ_BILLING_TABLE", "").strip()     # optional fully-qualified table or view

USE_FIRESTORE_CACHE  = os.getenv("USE_FIRESTORE_CACHE", "false").lower() == "true"

# Timing / cache knobs (ints)
def _as_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default

GCP_LOOKBACK_MIN     = _as_int("GCP_LOOKBACK_MIN", 10)
GCP_ALIGN_SEC        = _as_int("GCP_ALIGN_SEC", 30)
GCP_LAG_SEC          = _as_int("GCP_LAG_SEC", 15)
GCP_CACHE_TTL_SEC    = _as_int("GCP_CACHE_TTL_SEC", 20)

# ---------------- Credentials ----------------
from google.oauth2 import service_account
from google.auth import default as google_auth_default
from google.auth.credentials import Credentials

def _get_credentials() -> Optional[Credentials]:
    if GOOGLE_KEY_PATH and os.path.exists(GOOGLE_KEY_PATH):
        return service_account.Credentials.from_service_account_file(GOOGLE_KEY_PATH)
    creds, _ = google_auth_default(scopes=None)
    return creds

CREDS = _get_credentials()

def _resolve_project_id() -> str:
    if GCP_PROJECT_ID:
        return GCP_PROJECT_ID
    # Try to infer from service account credentials
    pid = getattr(CREDS, "project_id", None)
    if pid:
        return pid
    raise RuntimeError(
        "No GCP project id found. Set GCP_PROJECT_ID in .env or use a key that has project_id."
    )

PROJECT_ID = _resolve_project_id()

# ---------------- Clients ----------------
from google.cloud import bigquery, monitoring_v3, firestore

bq_client  = bigquery.Client(project=PROJECT_ID, credentials=CREDS)
mon_client = monitoring_v3.MetricServiceClient(credentials=CREDS)
mon_project_path = f"projects/{PROJECT_ID}"

fs_client: Optional[firestore.Client] = None
if USE_FIRESTORE_CACHE:
    fs_client = firestore.Client(project=PROJECT_ID, credentials=CREDS)

# ---------------- Helpers ----------------
def _billing_source() -> str:
    """
    Returns a table spec usable inside backticks: project.dataset.table_or_wildcard
    - Uses BQ_BILLING_TABLE if provided (supports full FQN like project.dataset.table or a view)
    - Otherwise defaults to the common wildcard inside the configured dataset.
    """
    if BQ_BILLING_TABLE:
        # If user passed dataset.table, prepend project. If they passed full FQN, keep as is.
        if BQ_BILLING_TABLE.count(".") == 1:
            return f"{PROJECT_ID}.{BQ_BILLING_TABLE}"
        return BQ_BILLING_TABLE
    # Default wildcard (export tables typically match gcp_billing_export_v1_* pattern)
    return f"{PROJECT_ID}.{BILLING_DATASET}.gcp_billing_export_v1_*"

def adc_smoke_test() -> Dict[str, Any]:
    """Quick sanity to confirm credentials and basic query works."""
    info: Dict[str, Any] = {
        "project": PROJECT_ID,
        "key_path": GOOGLE_KEY_PATH or "(ADC)",
        "billing_source": _billing_source(),
        "use_firestore_cache": USE_FIRESTORE_CACHE,
        "lookback_min": GCP_LOOKBACK_MIN,
        "align_sec": GCP_ALIGN_SEC,
        "lag_sec": GCP_LAG_SEC,
        "cache_ttl_sec": GCP_CACHE_TTL_SEC,
    }
    try:
        ok = list(bq_client.query("SELECT 1 AS ok").result())[0]["ok"]
        info["bq_ping"] = ok
    except Exception as e:
        info["bq_ping"] = f"ERROR: {e}"
    return info

# ---------------- Public API ----------------
def get_mtd_costs_by_project_service() -> List[Dict[str, Any]]:
    """
    Month-to-date cost by project+service from BigQuery billing export.
    Compatible with standard export schema (cost).
    """
    src = _billing_source()
    sql = f"""
    SELECT
      project.name AS project,
      service.description AS service,
      ROUND(SUM(COALESCE(cost, 0)), 2) AS mtd_cost
    FROM `{src}`
    WHERE usage_start_time >= TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), MONTH)
    GROUP BY 1,2
    ORDER BY mtd_cost DESC
    """
    return [dict(r) for r in bq_client.query(sql).result()]

def get_daily_cost_trend(days: int = 30) -> List[Dict[str, Any]]:
    """
    Daily cost trend for the last N days.
    """
    src = _billing_source()
    sql = f"""
    SELECT
      DATE(usage_start_time) AS day,
      ROUND(SUM(COALESCE(cost, 0)), 2) AS daily_cost
    FROM `{src}`
    WHERE usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY day
    ORDER BY day
    """
    return [{"day": str(r["day"]), "daily_cost": r["daily_cost"]} for r in bq_client.query(sql).result()]

# -------- Optional: Firestore cache helpers (no-ops if disabled) --------
def cache_put(key: str, value: Dict[str, Any]) -> None:
    if not fs_client:
        return
    fs_client.collection("saia_cache").document(key).set(value, merge=True)

def cache_get(key: str) -> Optional[Dict[str, Any]]:
    if not fs_client:
        return None
    doc = fs_client.collection("saia_cache").document(key).get()
    return doc.to_dict() if doc.exists else None

# -------- Example Monitoring helper (uses your timing knobs) --------
def list_cpu_util_timeseries(minutes: Optional[int] = None):
    """
    Example Cloud Monitoring read for GCE CPU utilization.
    """
    from google.protobuf import timestamp_pb2

    lookback = minutes or GCP_LOOKBACK_MIN
    end = dt.datetime.utcnow() - dt.timedelta(seconds=GCP_LAG_SEC)
    start = end - dt.timedelta(minutes=lookback)

    ts_end = timestamp_pb2.Timestamp(seconds=int(end.timestamp()))
    ts_start = timestamp_pb2.Timestamp(seconds=int(start.timestamp()))

    interval = monitoring_v3.TimeInterval(start_time=ts_start, end_time=ts_end)
    request = monitoring_v3.ListTimeSeriesRequest(
        name=mon_project_path,
        filter='metric.type="compute.googleapis.com/instance/cpu/utilization"',
        aggregation=monitoring_v3.Aggregation(
            alignment_period={"seconds": GCP_ALIGN_SEC},
            per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_MEAN,
        ),
        interval=interval,
        view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
    )
    return list(mon_client.list_time_series(request=request))
