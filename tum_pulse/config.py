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
BEDROCK_HAIKU_MODEL_ID: str = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
EMBEDDINGS_MODEL_ID: str = "amazon.titan-embed-text-v2:0"

# Database
DB_PATH: str = str(Path(__file__).parent / "data" / "tum_pulse.db")

# TUM / Moodle
TUM_USERNAME: str = os.getenv("TUM_USERNAME", "")
TUM_PASSWORD: str = os.getenv("TUM_PASSWORD", "")
MOODLE_BASE_URL: str = os.getenv("MOODLE_BASE_URL", "https://www.moodle.tum.de")

# ZHS (real booking platform)
ZHS_USERNAME: str = os.getenv("ZHS_USERNAME", TUM_USERNAME)
ZHS_PASSWORD: str = os.getenv("ZHS_PASSWORD", TUM_PASSWORD)
ZHS_URL: str = "https://kurse.zhs-muenchen.de"

# S3 storage
S3_BUCKET_NAME: str = os.getenv(
    "S3_BUCKET_NAME",
    f"tum-pulse-{(TUM_USERNAME or 'default').lower()}-{AWS_REGION}",
)

# Confluence / Collab Wiki
CONFLUENCE_URL: str = os.getenv("CONFLUENCE_URL", "https://collab.dvb.bayern")
CONFLUENCE_USERNAME: str = os.getenv("CONFLUENCE_USERNAME", TUM_USERNAME)
CONFLUENCE_PASSWORD: str = os.getenv("CONFLUENCE_PASSWORD", TUM_PASSWORD)
# Personal Access Token — required when basic auth is disabled (preferred over password)
CONFLUENCE_PAT: str = os.getenv("CONFLUENCE_PAT", "")
CONFLUENCE_SPACE: str = os.getenv("CONFLUENCE_SPACE", "")

# Screenshots / artifacts
DATA_DIR: str = str(Path(__file__).parent / "data")
