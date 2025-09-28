import os
from typing import List, Dict, Any
from google.cloud import bigquery

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BILLING_DATASET = os.getenv("BILLING_DATASET", "billing_export")

_bq = bigquery.Client(project=GCP_PROJECT_ID)

def get_mtd_costs_by_project_service() -> List[Dict[str, Any]]:
    """
    Month-to-date cost by project+service from BigQuery billing export.
    Dataset: <BILLING_DATASET>.gcp_billing_export_v1_*
    """
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
    """
    Daily cost trend for the last N days.
    """
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
