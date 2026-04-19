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

# Moodle
MOODLE_BASE_URL: str = os.getenv("MOODLE_BASE_URL", "https://www.moodle.tum.de")

# ZHS URL (static)
ZHS_URL: str = "https://kurse.zhs-muenchen.de"

# Confluence URL (static)
CONFLUENCE_URL: str = os.getenv("CONFLUENCE_URL", "https://collab.dvb.bayern")
CONFLUENCE_SPACE: str = os.getenv("CONFLUENCE_SPACE", "")

# Screenshots / artifacts
DATA_DIR: str = str(Path(__file__).parent / "data")


# ---------------------------------------------------------------------------
# Credential accessors — always read from os.environ so they pick up values
# written by the login form without requiring a process restart.
# ---------------------------------------------------------------------------

def get_tum_username() -> str:
    return os.environ.get("TUM_USERNAME", "")

def get_tum_password() -> str:
    return os.environ.get("TUM_PASSWORD", "")

def get_zhs_username() -> str:
    return os.environ.get("ZHS_USERNAME", "") or get_tum_username()

def get_zhs_password() -> str:
    return os.environ.get("ZHS_PASSWORD", "") or get_tum_password()

def get_confluence_username() -> str:
    return os.environ.get("CONFLUENCE_USERNAME", "") or get_tum_username()

def get_confluence_password() -> str:
    return os.environ.get("CONFLUENCE_PASSWORD", "") or get_tum_password()

def get_confluence_pat() -> str:
    return os.environ.get("CONFLUENCE_PAT", "")

def get_s3_bucket() -> str:
    name = os.environ.get("S3_BUCKET_NAME", "")
    if not name:
        user = (get_tum_username() or "default").lower()
        name = f"tum-pulse-{user}-{AWS_REGION}"
    return name


# ---------------------------------------------------------------------------
# Legacy module-level names — kept for backward compatibility.
# These are read once at import; code that needs live values should call
# the get_*() functions above instead.
# ---------------------------------------------------------------------------

TUM_USERNAME: str = os.getenv("TUM_USERNAME", "")
TUM_PASSWORD: str = os.getenv("TUM_PASSWORD", "")
ZHS_USERNAME: str = os.getenv("ZHS_USERNAME", TUM_USERNAME)
ZHS_PASSWORD: str = os.getenv("ZHS_PASSWORD", TUM_PASSWORD)
CONFLUENCE_USERNAME: str = os.getenv("CONFLUENCE_USERNAME", TUM_USERNAME)
CONFLUENCE_PASSWORD: str = os.getenv("CONFLUENCE_PASSWORD", TUM_PASSWORD)
CONFLUENCE_PAT: str = os.getenv("CONFLUENCE_PAT", "")
S3_BUCKET_NAME: str = os.getenv(
    "S3_BUCKET_NAME",
    f"tum-pulse-{(TUM_USERNAME or 'default').lower()}-{AWS_REGION}",
)
