import os
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# MODEL = "deepseek-chat"
# BASE_URL = "https://api.deepseek.com"

MODEL = "deepseek/deepseek-chat"
BASE_URL = "https://openrouter.ai/api/v1"

INPUT_FOLDER = "final_files"
OUTPUT_FILE = "output/grades.csv"

MAX_WORKERS = 8
MAX_RETRIES = 3
TIMEOUT = 60