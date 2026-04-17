"""Central configuration for TUM Pulse."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# AWS
AWS_REGION: str = os.getenv("AWS_REGION", "eu-central-1")
AWS_ACCESS_KEY_ID: str = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")

# Bedrock model IDs (EU inference profiles)
BEDROCK_MODEL_ID: str = "eu.anthropic.claude-sonnet-4-6"
EMBEDDINGS_MODEL_ID: str = "amazon.titan-embed-text-v2:0"

# Database
DB_PATH: str = str(Path(__file__).parent / "data" / "tum_pulse.db")

# TUM / Moodle
TUM_USERNAME: str = os.getenv("TUM_USERNAME", "")
TUM_PASSWORD: str = os.getenv("TUM_PASSWORD", "")
MOODLE_BASE_URL: str = os.getenv("MOODLE_BASE_URL", "https://www.moodle.tum.de")

# ZHS
ZHS_USERNAME: str = os.getenv("ZHS_USERNAME", "")
ZHS_PASSWORD: str = os.getenv("ZHS_PASSWORD", "")
ZHS_URL: str = "https://www.zhs-muenchen.de"

# Screenshots / artifacts
DATA_DIR: str = str(Path(__file__).parent / "data")
