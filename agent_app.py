# agent_app.py
import os
from vertexai.preview.generative_models import GenerativeModel
from services import gcp_connector


def create_cloud_audit_agent():
    """Creates the Vertex AI agent that audits GCP costs (AWS/Azure dummy dropped)."""
    model = GenerativeModel("gemini-2.5-pro")  # ✅ Use Vertex AI Gemini

    def cloud_audit(user_input: str):
        try:
            # --- GCP ---
            gcp_real = gcp_connector.get_mtd_costs_by_project_service()
            gcp_total = sum([r["mtd_cost"] for r in gcp_real])
        except Exception as e:
            print("DEBUG: GCP cost fetch failed:", e)
            gcp_real, gcp_total = [], 120.50  # fallback dummy

        # --- Build summary (like overview) ---
        gcp_lines = "\n".join(
            [f"- {r['project']} | {r['service']} → ${r['mtd_cost']:.2f}" for r in gcp_real[:5]]
        ) or "No GCP data available."

        full_summary = (
            f"=== Google Cloud ===\n"
            f"Total: ${gcp_total:.2f}\n"
            f"{gcp_lines}\n"
        )

        # --- Prompt for Vertex AI ---
        prompt = (
            "You are CloudLens AI, a smart cloud auditor.\n"
            "ONLY use the provided data. Keep it short and helpful.\n"
            "- Max 5 concise bullet points (≤100 words).\n"
            "- Include: total spend, top costly services, and 1–2 optimizations.\n\n"
            f"DATA:\n{full_summary}\n\n"
            f"User: {user_input}\n\n"
            "⚠️ Do not invent facts not in the data."
        )

        try:
            response = model.generate_content(prompt)
            return response.text.strip() if response and response.text else "⚠️ No response from AI."
        except Exception as e:
            print("DEBUG ERROR in cloud_audit:", e)
            return f"⚠️ Error: {e}"

    return cloud_audit
