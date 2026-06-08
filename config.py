"""VendorFAIR configuration loader."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
APP_TITLE = os.getenv("APP_TITLE", "VendorFAIR")
ORG_NAME = os.getenv("ORG_NAME", "Your MSP Name")
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "vendorfair.db"))
REPORT_OUTPUT_DIR = os.getenv("REPORT_OUTPUT_DIR", str(BASE_DIR / "reports"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DEFAULT_MONTE_CARLO_ITERATIONS = int(os.getenv("DEFAULT_MONTE_CARLO_ITERATIONS", "10000"))

# Note: the original plan specified claude-sonnet-4-20250514, which is deprecated
# and retires June 15, 2026. claude-sonnet-4-6 is its official replacement.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Local research fallback (Ollama). Used when no API key is configured for the
# selected cloud provider. Ollama stays bound to localhost by default.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")

# Ensure runtime directories exist
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
Path(REPORT_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
