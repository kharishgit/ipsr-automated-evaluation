import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Select provider without code edits:
# - Set `LLM_PROVIDER=gemini` or `LLM_PROVIDER=openrouter` in `.env`
# - If unset, it defaults to gemini when GEMINI_API_KEY is present; otherwise openrouter.
LLM_PROVIDER = os.getenv("LLM_PROVIDER") or ("gemini" if GEMINI_API_KEY else "openrouter")

# Gemini model name
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"


# DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# OpenRouter (OpenAI-compatible) model name + base URL
MODEL = os.getenv("OPENROUTER_MODEL") or "deepseek/deepseek-chat"
BASE_URL = os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"

INPUT_FOLDER = "final_files"
OUTPUT_FILE = "output/grades.csv"

MAX_WORKERS = 8
MAX_RETRIES = 3
TIMEOUT = 60

# Optional end-to-end mode (valuation.py):
# If a Moodle ZIP is present in the repo root, valuation.py can unzip it and then
# extract student files before grading.
SUBMISSIONS_DIR = "Submissions"
FINAL_FILES_DIR = "final_files"
AUTO_DETECT_MOODLE_ZIP = True
MOODLE_ZIP_PATH = ""  # If set, valuation.py uses this path instead of auto-detecting.
