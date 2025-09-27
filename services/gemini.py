# services/gemini.py
import os
import google.generativeai as genai

# Load API key from environment
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("⚠️ No GEMINI_API_KEY found in environment")

genai.configure(api_key=API_KEY)

# MODEL
MODEL = genai.GenerativeModel("gemini-2.5-flash")

def summarize_costs(data):
    """
    Summarize cloud cost data into a human-readable insight.
    """
    try:
        text_input = "Here is cloud provider cost data:\n"
        for item in data:
            text_input += f"- {item['provider'].upper()}: ${item['cost']}\n"

        text_input += "\nWrite a short business-friendly summary (5–10 sentences)."

        response = MODEL.generate_content(text_input)
        return response.text.strip() if response and response.text else "No summary generated."
    except Exception as e:
        return f"⚠️ Gemini error: {e}"
        
