# agent_app.py
import os
import vertexai
from typing import Any, Dict
from vertexai.generative_models import GenerativeModel, FunctionDeclaration, Tool

# ---- Import your live connectors from services ----
from services import gcp_connector, gcp_live

# ----- Vertex init -----
PROJECT_ID = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION   = os.getenv("GCP_REGION", "us-central1")
if not PROJECT_ID:
    raise RuntimeError("GCP_PROJECT_ID (or GOOGLE_CLOUD_PROJECT) must be set")
vertexai.init(project=PROJECT_ID, location=LOCATION)

# ----- Tool functions (Python side) -----
def _get_mtd_costs() -> list[dict[str, Any]]:
    return gcp_connector.get_mtd_costs_by_project_service()

def _get_daily_cost_trend(days: int = 30) -> list[dict[str, Any]]:
    return gcp_connector.get_daily_cost_trend(days=days)

def _tiles_summary() -> dict[str, Any]:
    return gcp_live.tiles_summary()

def _cpu_timeseries(minutes: int = 30, step_seconds: int = 60) -> dict[str, Any]:
    return gcp_live.cpu_timeseries(minutes=minutes, step_seconds=step_seconds)

def _traffic_timeseries(minutes: int = 30, step_seconds: int = 60) -> dict[str, Any]:
    return gcp_live.traffic_timeseries(minutes=minutes, step_seconds=step_seconds)

# ----- Function Declarations (schema the model sees) -----
fd_get_mtd_costs = FunctionDeclaration(
    name="get_mtd_costs",
    description="Get month-to-date GCP costs grouped by project and service.",
    parameters={"type": "object", "properties": {}},
)

fd_get_daily_cost_trend = FunctionDeclaration(
    name="get_daily_cost_trend",
    description="Get daily GCP costs for the last N days.",
    parameters={
        "type": "object",
        "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 365}},
        "required": ["days"],
    },
)

fd_tiles_summary = FunctionDeclaration(
    name="tiles_summary",
    description="Get VM health tiles: CPU %, net in/out, disk read/write, error count (5m).",
    parameters={"type": "object", "properties": {}},
)

fd_cpu_timeseries = FunctionDeclaration(
    name="cpu_timeseries",
    description="Get CPU percent time-series.",
    parameters={
        "type": "object",
        "properties": {
            "minutes": {"type": "integer", "minimum": 1, "maximum": 240},
            "step_seconds": {"type": "integer", "minimum": 5, "maximum": 600},
        },
        "required": ["minutes", "step_seconds"],
    },
)

fd_traffic_timeseries = FunctionDeclaration(
    name="traffic_timeseries",
    description="Get network ingress/egress (Mbps) time-series.",
    parameters={
        "type": "object",
        "properties": {
            "minutes": {"type": "integer", "minimum": 1, "maximum": 240},
            "step_seconds": {"type": "integer", "minimum": 5, "maximum": 600},
        },
        "required": ["minutes", "step_seconds"],
    },
)

tools = [Tool(function_declarations=[
    fd_get_mtd_costs,
    fd_get_daily_cost_trend,
    fd_tiles_summary,
    fd_cpu_timeseries,
    fd_traffic_timeseries,
])]

SYSTEM_PROMPT = (
    "You are CloudLens AI. Answer questions about GCP spend and live VM metrics.\n"
    "- For spend: call get_mtd_costs and/or get_daily_cost_trend.\n"
    "- For live health: call tiles_summary, cpu_timeseries, or traffic_timeseries.\n"
    "Be concise, include numbers, and give 1–2 actionable tips."
)

_EXEC_MAP = {
    "get_mtd_costs": lambda **kw: _get_mtd_costs(),
    "get_daily_cost_trend": lambda **kw: _get_daily_cost_trend(int(kw.get("days", 30))),
    "tiles_summary": lambda **kw: _tiles_summary(),
    "cpu_timeseries": lambda **kw: _cpu_timeseries(
        minutes=int(kw.get("minutes", 30)), step_seconds=int(kw.get("step_seconds", 60))
    ),
    "traffic_timeseries": lambda **kw: _traffic_timeseries(
        minutes=int(kw.get("minutes", 30)), step_seconds=int(kw.get("step_seconds", 60))
    ),
}

class CloudAuditAgent:
    def __init__(self, model_name: str = "gemini-2.5-pro"):
        self.model = GenerativeModel(model_name=model_name, system_instruction=SYSTEM_PROMPT)

    def chat(self, query: str) -> dict:
        calls: list[Dict[str, Any]] = []
        chat = self.model.start_chat(history=[])
        resp = chat.send_message(query, tools=tools)

        for _ in range(6):  # up to 6 tool calls
            if not getattr(resp, "candidates", None):
                break

            fcs = getattr(resp.candidates[0], "function_calls", None)
            if not fcs:
                # final text
                parts = getattr(resp.candidates[0].content, "parts", [])
                text = "".join([getattr(p, "text", "") for p in parts])
                return {"text": text.strip() or "No response.", "calls": calls}

            fc = fcs[-1]
            name = fc.name
            args = dict(fc.args) if hasattr(fc, "args") else {}

            try:
                fn = _EXEC_MAP.get(name)
                if not fn:
                    raise ValueError(f"Unknown tool: {name}")
                result = fn(**args)
                calls.append({"name": name, "args": args, "ok": True})
                # send back tool response (dict form, no FunctionResponse)
                resp = chat.send_message({
                    "function_response": {
                        "name": name,
                        "response": result
                    }
                })
            except Exception as e:
                calls.append({"name": name, "args": args, "ok": False, "error": str(e)})
                resp = chat.send_message({
                    "function_response": {
                        "name": name,
                        "response": {"error": str(e)}
                    }
                })

        # fallback
        parts = getattr(resp.candidates[0].content, "parts", [])
        text = "".join([getattr(p, "text", "") for p in parts])
        return {"text": text.strip() or "(no final text)", "calls": calls}

def create_cloud_audit_agent() -> CloudAuditAgent:
    return CloudAuditAgent(model_name=os.getenv("VERTEX_MODEL", "gemini-2.5-pro"))
