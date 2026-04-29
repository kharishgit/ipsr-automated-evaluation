import os
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import pandas as pd
from prompt_builder import build_prompt
from rule_engine import rule_check
import config
from extract import extract_student_files
from unzip_submissions import unzip_to_submissions
from openai import OpenAI

# ==============================
# SETUP
# ==============================
os.makedirs("logs", exist_ok=True)
os.makedirs("output", exist_ok=True)

logging.basicConfig(
    filename="logs/grading.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger("").addHandler(console)

def _get_openrouter_client() -> OpenAI:
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("Missing DEEPSEEK_API_KEY in environment/.env")
    return OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=getattr(config, "BASE_URL", "https://openrouter.ai/api/v1"),
        default_headers={
            "HTTP-Referer": "http://localhost",
            "X-Title": "grading-app",
        },
    )


def _get_gemini_model():
    if not config.GEMINI_API_KEY:
        raise RuntimeError("Missing GEMINI_API_KEY in environment/.env")
    try:
        import google.generativeai as genai  # type: ignore
    except Exception as e:
        raise RuntimeError(f"google-generativeai is not installed: {e}")

    genai.configure(api_key=config.GEMINI_API_KEY)
    return genai.GenerativeModel(
        getattr(config, "GEMINI_MODEL", "gemini-2.5-flash"),
        generation_config={"temperature": 0},
    )
# ==============================
# LOAD RUBRIC
# ==============================
def load_rubric():
    with open("rubric.json", "r") as f:
        return json.load(f)


def _find_moodle_zip_in_repo_root() -> str | None:
    if config.MOODLE_ZIP_PATH:
        return config.MOODLE_ZIP_PATH
    if not getattr(config, "AUTO_DETECT_MOODLE_ZIP", True):
        return None

    zips = []
    for name in os.listdir("."):
        if name.lower().endswith(".zip") and os.path.isfile(name):
            zips.append(name)
    if not zips:
        return None

    zips.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return zips[0]


def _prepare_inputs() -> None:
    zip_path = _find_moodle_zip_in_repo_root()
    if not zip_path:
        return

    submissions_dir = getattr(config, "SUBMISSIONS_DIR", "Submissions")
    final_files_dir = getattr(config, "FINAL_FILES_DIR", "final_files")

    # Clean previous runs so each valuation is fresh.
    _clean_dir_contents(submissions_dir)
    _clean_dir_contents(final_files_dir)

    zip_stem = os.path.splitext(os.path.basename(zip_path))[0]
    # Extract into a dedicated subfolder to avoid mixing old submissions.
    extracted_root = os.path.join(submissions_dir, f"_zip_{zip_stem}")
    os.makedirs(extracted_root, exist_ok=True)

    logging.info(f"Found Moodle ZIP: {zip_path}. Extracting to: {extracted_root}")
    rc = unzip_to_submissions(zip_path, extracted_root, overwrite=True)
    if rc != 0:
        raise RuntimeError(f"Unzip failed with code {rc}")

    logging.info(f"Extracting student files from {extracted_root} to {final_files_dir}")
    rc2 = extract_student_files(source_folder=extracted_root, destination_folder=final_files_dir)
    if rc2 != 0:
        raise RuntimeError(f"Extraction failed with code {rc2}")


def _clean_dir_contents(path: str) -> None:
    if not os.path.isdir(path):
        return
    for name in os.listdir(path):
        if name in {".gitkeep", ".keep"}:
            continue
        full = os.path.join(path, name)
        try:
            if os.path.isdir(full) and not os.path.islink(full):
                import shutil

                shutil.rmtree(full)
            else:
                os.remove(full)
        except Exception as e:
            logging.warning(f"Failed to delete {full}: {e}")

# ==============================
# FILE TO TEXT
# ==============================
import fitz
import pytesseract
from PIL import Image

def pdf_to_text(file_path, max_chars=5000):
    text = ""
    try:
        doc = fitz.open(file_path)

        for page in doc:
            text += page.get_text()

        # OCR fallback
        if len(text.strip()) < 50:
            logging.info(f"OCR used for {file_path}")
            text = ""
            for page in doc:
                pix = page.get_pixmap()
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                text += pytesseract.image_to_string(img)

        return text[:max_chars]

    except Exception as e:
        logging.error(f"PDF error: {file_path} | {e}")
        return ""


def file_to_text(file_path, max_rows=50):
    try:
        ext = os.path.splitext(file_path)[1].lower()

        if ext in [".xlsx", ".xls"]:
            df_dict = pd.read_excel(file_path, sheet_name=None, engine="openpyxl")  # read all sheets

            all_text = ""

            for sheet_name, df in df_dict.items():
                # all_text += f"\nSheet: {sheet_name}\n"
                all_text += f"\nSheet: {sheet_name} (IMPORTANT)\n"
                if df.empty:
                    all_text += f"\nSheet: {sheet_name} is empty\n"
                else:
                    
                    # safe_df = df.head(max_rows).astype(str)
                    safe_df = df.head(max_rows).astype(str)
                    all_text += json.dumps(safe_df.to_dict(), indent=2)
                    
                all_text += "\n"

            return all_text[:5000]

        elif ext == ".csv":
            df = pd.read_csv(file_path)
            return df.head(max_rows).to_string()

        elif ext == ".txt":
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()[:5000]

        elif ext == ".json":
            with open(file_path, "r") as f:
                return json.dumps(json.load(f))[:5000]

        elif ext == ".pdf":
            return pdf_to_text(file_path)

        else:
            logging.warning(f"Unsupported file: {file_path}")
            return ""

    except Exception as e:
        logging.error(f"Error reading {file_path}: {e}")
        return ""



# ==============================
# API CALL WITH RETRIES
# ==============================
import re

def extract_json(text):
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        pass
    return None
def call_api(prompt):
    for attempt in range(config.MAX_RETRIES):
        try:
            provider = getattr(config, "LLM_PROVIDER", "gemini")
            if provider == "gemini":
                model = _get_gemini_model()
                response = model.generate_content(prompt)
                content = response.text.strip() if getattr(response, "text", None) else ""
            else:
                client = _get_openrouter_client()
                response = client.chat.completions.create(
                    model=config.MODEL,
                    temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = response.choices[0].message.content.strip()
            
            
            
            # Try direct JSON
            try:
                return json.loads(content)
            except:
                pass

            # Try extracting JSON from messy output
            parsed = extract_json(content)
            if parsed:
                return parsed

            logging.warning(f"Invalid JSON response: {content}")

        except Exception as e:
            logging.warning(f"Retry {attempt+1} failed: {e}")
            time.sleep(2 ** attempt)

    return {"marks": 0, "reason": "API failure"}
# ==============================
# PROCESS FILE
# ==============================
def process_file(file_name, rubric):
    path = os.path.join(config.INPUT_FOLDER, file_name)
    ext = os.path.splitext(path)[1].lower()

# Decide grading mode
    if ext == ".pdf":
        mode = "lenient"
    else:
        mode = "strict"
    name_part = os.path.splitext(file_name)[0]
    parts = name_part.split()

    student = "_".join(parts[:2]) if len(parts) >= 2 else parts[0]

    logging.info(f"Processing {student}")

    text = file_to_text(path)
    # print("TEXT SAMPLE:", text[:500])

    if not text:
        return {"student": student, "marks": 0, "reason": "Unreadable file"}

    # Rule-based score
    rule_score = rule_check(text)

    # AI score
    prompt = build_prompt(rubric, text, mode)
    ai_result = call_api(prompt)

    ai_marks = ai_result.get("marks", 0)
    reason = ai_result.get("reason", "")

    # 🔁 Re-evaluate if marks are low
    if ai_marks < 60:
        logging.info(f"Re-evaluating {student} due to low score: {ai_marks}")
        
        scores = [ai_marks]

        for _ in range(2):  # retry 2 more times (total 3)
            retry_result = call_api(prompt)
            retry_marks = retry_result.get("marks", 0)
            scores.append(retry_marks)

        # Take average
        ai_marks = int(sum(scores) / len(scores))

    final_marks = min(rubric["total_marks"], rule_score + ai_marks)

    if final_marks >= rubric["threshold"]:
        reason = ""

    return {
        "student": student,
        "marks": final_marks,
        "reason": reason
    }

# ==============================
# MAIN
# ==============================
def main():
    _prepare_inputs()
    rubric = load_rubric()

    files = [f for f in os.listdir(config.INPUT_FOLDER) if not f.startswith(".")]

    logging.info(f"Total files: {len(files)}")

    results = []

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        futures = [executor.submit(process_file, f, rubric) for f in files]

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                logging.error(f"Error: {e}")

    df = pd.DataFrame(results)
    df.sort_values("student", inplace=True)

    df.rename(columns={
    "student": "Full name",
    "marks": "Grade",
    "reason": "Feedback comments"
}, inplace=True)

    df.to_csv(config.OUTPUT_FILE, index=False)

    logging.info(f"✅ Done. Output saved to {config.OUTPUT_FILE}")

# ==============================
if __name__ == "__main__":
    main()
