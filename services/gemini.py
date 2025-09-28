import os
from typing import List, Dict

def summarize_costs(rows: List[Dict]) -> str:
    """
    Lightweight summarizer fallback: no external API calls.
    Then leave a space to continue to give 5-6 summary. Highlight key words.
    
    """
    if not rows:
        return "No cost data available yet."
    providers = {}
    for r in rows:
        prov = r.get("provider", "unknown")
        providers.setdefault(prov, 0.0)
        providers[prov] += float(r.get("cost", 0.0))
    parts = [f"{k.upper()}: ${v:.2f}" for k, v in providers.items()]
    total = sum(providers.values())
    return f"Current spend — {' | '.join(parts)}. Total: ${total:.2f}."
