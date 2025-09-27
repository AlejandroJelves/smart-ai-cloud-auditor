from services import gcp_connector

try:
    print("🔎 Testing MTD costs...")
    data = gcp_connector.get_mtd_costs_by_project_service()
    print("✅ Got data:", data)
except Exception as e:
    print("❌ Error:", e)
