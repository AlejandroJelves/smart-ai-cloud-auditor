import os
from dotenv import load_dotenv
import vertexai

# Load env vars
load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
REGION = os.getenv("GCP_REGION", "us-central1")

# Init Vertex AI
vertexai.init(project=PROJECT_ID, location=REGION)

# Import your agent after init
from . import agent_app
