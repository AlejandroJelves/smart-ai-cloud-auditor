import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from google.cloud import monitoring_v3
from google.api_core.exceptions import InvalidArgument

import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from google.cloud import monitoring_v3
from google.oauth2 import service_account

PROJECT_ID = os.getenv("GCP_PROJECT_ID")

def _creds():
    sa = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if sa and os.path.exists(sa):
        return service_account.Credentials.from_service_account_file(sa)
    return None  # fall back to ADC if available

def _client() -> monitoring_v3.MetricServiceClient:
    return monitoring_v3.MetricServiceClient(credentials=_creds())

def _project_name() -> str:
    if not PROJECT_ID:
        raise ValueError("GCP_PROJECT_ID not set")
    return f"projects/{PROJECT_ID}"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _interval_minutes(minutes: int):
    end = _now_utc()
    start = end - timedelta(minutes=minutes)
    return monitoring_v3.TimeInterval(
        end_time={"seconds": int(end.timestamp())},
        start_time={"seconds": int(start.timestamp())},
    )

def _list_series(metric_filter: str, interval, alignment_seconds: int,
                 aligner: monitoring_v3.Aggregation.Aligner,
                 reducer: monitoring_v3.Aggregation.Reducer):
    try:
        return list(_client().list_time_series(
            request={
                "name": _project_name(),
                "filter": metric_filter,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                "aggregation": monitoring_v3.Aggregation(
                    alignment_period={"seconds": alignment_seconds},
                    per_series_aligner=aligner,
                    cross_series_reducer=reducer,
                ),
            }
        ))
    except Exception as e:
        # Fail safe : return empty
        print("[monitoring] list_time_series error:", e)
        return []

# ---- TILES ----
def vm_cpu_avg_last_5m() -> float:
    interval = _interval_minutes(5)
    series = _list_series(
        'metric.type="compute.googleapis.com/instance/cpu/utilization"',
        interval, 300,
        monitoring_v3.Aggregation.Aligner.ALIGN_MEAN,
        monitoring_v3.Aggregation.Reducer.REDUCE_MEAN
    )
    vals = []
    for ts in series:
        for p in ts.points:
            if p.value.double_value is not None:
                vals.append(p.value.double_value)
    # Return the mean across VMs in percent, capped 0..100
    pct = round(100.0 * (sum(vals)/len(vals)), 1) if vals else 0.0
    return max(0.0, min(100.0, pct))

def vm_traffic_tile_last_5m() -> Dict[str, float]:
    interval = _interval_minutes(5)

    def _sum_rate(metric_type: str) -> float:
        series = _list_series(
            f'metric.type="{metric_type}"', interval, 300,
            monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
            monitoring_v3.Aggregation.Reducer.REDUCE_SUM
        )
        bps = 0.0
        for ts in series:
            for p in ts.points:
                if p.value.double_value is not None:
                    bps += p.value.double_value  # bytes/sec
        return round((bps * 8.0) / 1_000_000.0, 2)  # Mbps

    return {
        "mbps_in":  _sum_rate("compute.googleapis.com/instance/network/received_bytes_count"),
        "mbps_out": _sum_rate("compute.googleapis.com/instance/network/sent_bytes_count"),
    }

def vm_disk_rw_tile_last_5m() -> Dict[str, float]:
    interval = _interval_minutes(5)

    def _sum_rate(metric_type: str) -> float:
        series = _list_series(
            f'metric.type="{metric_type}"', interval, 300,
            monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
            monitoring_v3.Aggregation.Reducer.REDUCE_SUM
        )
        bps = 0.0
        for ts in series:
            for p in ts.points:
                if p.value.double_value is not None:
                    bps += p.value.double_value  # bytes/sec
        return round(bps / 1_000_000.0, 2)  # MB/s

    return {
        "read_mbs":  _sum_rate("compute.googleapis.com/instance/disk/read_bytes_count"),
        "write_mbs": _sum_rate("compute.googleapis.com/instance/disk/write_bytes_count"),
    }

def error_logs_count_last_5m() -> int:
    """
    Count ERROR/CRITICAL/ALERT/EMERGENCY log entries via logging metric (if defined).
    If not enabled in your project, it will return 0 safely.
    """
    interval = _interval_minutes(5)
    sev_filter = (
        'metric.labels.severity="ERROR" OR '
        'metric.labels.severity="CRITICAL" OR '
        'metric.labels.severity="ALERT" OR '
        'metric.labels.severity="EMERGENCY"'
    )
    mfilter = (
        'metric.type="logging.googleapis.com/log_entry_count" '
        f'AND resource.type="gce_instance" AND ({sev_filter})'
    )
    try:
        series = _list_series(
            mfilter, interval, 300,
            monitoring_v3.Aggregation.Aligner.ALIGN_SUM,
            monitoring_v3.Aggregation.Reducer.REDUCE_SUM
        )
        total = 0
        for ts in series:
            for p in ts.points:
                v = getattr(p.value, "int64_value", None)
                if v is not None:
                    total += int(v)
        return total
    except InvalidArgument:
        return 0
    except Exception:
        return 0

# ---- Time Series for charts ----
def traffic_timeseries(minutes: int = 30, step_seconds: int = 60) -> Dict[str, List]:
    interval = _interval_minutes(minutes)

    def _series(metric_type: str) -> Dict[str, float]:
        ser = _list_series(
            f'metric.type="{metric_type}"',
            interval, step_seconds,
            monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
            monitoring_v3.Aggregation.Reducer.REDUCE_SUM
        )
        by_ts: Dict[str, float] = {}
        for ts in ser:
            for p in ts.points:
                t = p.interval.end_time
                if hasattr(t, "ToDatetime"):
                    t_iso = t.ToDatetime().astimezone(timezone.utc).isoformat()
                else:
                    t_iso = datetime.fromtimestamp(t.seconds, tz=timezone.utc).isoformat()
                mbps = (p.value.double_value or 0.0) * 8.0 / 1_000_000.0
                by_ts[t_iso] = by_ts.get(t_iso, 0.0) + mbps
        return by_ts

    ins  = _series("compute.googleapis.com/instance/network/received_bytes_count")
    outs = _series("compute.googleapis.com/instance/network/sent_bytes_count")

    timeline = sorted(set(ins.keys()) | set(outs.keys()))
    return {
        "ts": timeline,
        "mbps_in":  [round(ins.get(t, 0.0), 3) for t in timeline],
        "mbps_out": [round(outs.get(t, 0.0), 3) for t in timeline],
    }

def cpu_timeseries(minutes: int = 30, step_seconds: int = 60) -> Dict[str, List]:
    interval = _interval_minutes(minutes)
    ser = _list_series(
        'metric.type="compute.googleapis.com/instance/cpu/utilization"',
        interval, step_seconds,
        monitoring_v3.Aggregation.Aligner.ALIGN_MEAN,
        monitoring_v3.Aggregation.Reducer.REDUCE_MEAN
    )
    by_ts = {}
    for ts in ser:
        for p in ts.points:
            t = p.interval.end_time
            if hasattr(t, "ToDatetime"):
                t_iso = t.ToDatetime().astimezone(timezone.utc).isoformat()
            else:
                t_iso = datetime.fromtimestamp(t.seconds, tz=timezone.utc).isoformat()
            pct = (p.value.double_value or 0.0) * 100.0
            by_ts.setdefault(t_iso, []).append(pct)

    ts_sorted = sorted(by_ts.keys())
    return {
        "ts": ts_sorted,
        "cpu_percent": [round(sum(by_ts[t]) / max(1, len(by_ts[t])), 2) for t in ts_sorted]
    }

# ---- Convenience bundle for tiles ----
def tiles_summary():
    return {
        "updated_at": _now_utc().isoformat(),
        "cpu_percent": vm_cpu_avg_last_5m(),
        "traffic": vm_traffic_tile_last_5m(),
        "disk": vm_disk_rw_tile_last_5m(),
        "errors_5m": error_logs_count_last_5m(),
    }
