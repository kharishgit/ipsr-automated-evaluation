import json
import os
import tempfile
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError

from openai import OpenAI

import config
import generator


app = FastAPI(title="IPSR Grading API")


class RubricCriterion(BaseModel):
    name: str
    marks: int = Field(ge=0)
    description: str


class Rubric(BaseModel):
    total_marks: int = Field(gt=0)
    threshold: int = Field(ge=0)
    criteria: list[RubricCriterion]
    instructions: str | None = None


class UpdateRequest(BaseModel):
    text: str = Field(min_length=1, description="Natural-language instruction for the LLM")


class QuestionUpload(BaseModel):
    question: str = Field(min_length=1, description="Assignment question text")


class RunRequest(BaseModel):
    total_marks: int = Field(default=100, gt=0)
    threshold: int = Field(default=60, ge=0)


def _atomic_write_text(path: str, content: str) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


def _load_rubric_from_disk(path: str = "rubric.json") -> Rubric:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return Rubric.model_validate(raw)


def _validate_rubric_json_bytes(data: bytes) -> dict[str, Any]:
    try:
        raw = json.loads(data.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    try:
        rubric = Rubric.model_validate(raw)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=json.loads(e.json()))
    return rubric.model_dump()


def _llm_client() -> OpenAI:
    # API generation/edit endpoints use OpenRouter (OpenAI-compatible) today.
    if not config.DEEPSEEK_API_KEY:
        raise HTTPException(status_code=500, detail="Missing DEEPSEEK_API_KEY in environment/.env (needed for API generation endpoints)")
    return OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.BASE_URL)


def _completion_fn():
    provider = getattr(config, "LLM_PROVIDER", "gemini")
    if provider == "gemini":
        if not config.GEMINI_API_KEY:
            raise HTTPException(status_code=500, detail="Missing GEMINI_API_KEY in environment/.env")
        try:
            import google.generativeai as genai  # type: ignore
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"google-generativeai not installed: {e}")
        genai.configure(api_key=config.GEMINI_API_KEY)
        model = genai.GenerativeModel(getattr(config, "GEMINI_MODEL", "gemini-2.5-flash"), generation_config={"temperature": 0})

        def _complete(system: str, user: str) -> str:
            prompt = f"{system}\n\n{user}"
            resp = model.generate_content(prompt)
            return (resp.text or "").strip()

        return _complete

    client = _llm_client()

    def _complete(system: str, user: str) -> str:
        resp = client.chat.completions.create(
            model=getattr(config, "MODEL", "deepseek/deepseek-chat"),
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return (resp.choices[0].message.content or "").strip()

    return _complete


def _generate_rule_engine(text: str, rubric: dict[str, Any]) -> str:
    try:
        complete = _completion_fn()
        return generator.generate_rule_engine(text, rubric, complete=complete)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _generate_prompt_builder(text: str, rubric: dict[str, Any]) -> str:
    try:
        complete = _completion_fn()
        return generator.generate_prompt_builder(text, rubric, complete=complete)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _validate_runtime(*, require_inputs: bool = True) -> None:
    # 1) rubric.json parses and matches schema
    rubric = _load_rubric_from_disk().model_dump()
    # 2) rule_engine.py and prompt_builder.py compile and expose required callables
    import importlib
    import sys

    importlib.invalidate_caches()

    def _import_or_reload(name: str):
        if name in sys.modules:
            return importlib.reload(sys.modules[name])
        return importlib.import_module(name)

    rule_engine = _import_or_reload("rule_engine")
    prompt_builder = _import_or_reload("prompt_builder")

    if not hasattr(rule_engine, "rule_check") or not callable(rule_engine.rule_check):
        raise HTTPException(status_code=400, detail="rule_engine.py is missing callable rule_check()")
    if not hasattr(prompt_builder, "build_prompt") or not callable(prompt_builder.build_prompt):
        raise HTTPException(status_code=400, detail="prompt_builder.py is missing callable build_prompt()")

    # 3) quick sanity: prompt_builder returns string for a trivial sample
    sample_prompt = prompt_builder.build_prompt(rubric, "SAMPLE", mode="lenient")
    if not isinstance(sample_prompt, str) or len(sample_prompt.strip()) == 0:
        raise HTTPException(status_code=400, detail="build_prompt() did not return a non-empty string")

    # 4) input folder exists and has files (so /grade/run is meaningful)
    if require_inputs:
        input_dir = config.INPUT_FOLDER
        if not os.path.isdir(input_dir):
            raise HTTPException(status_code=400, detail=f"Missing input folder: {input_dir}")
        files = [f for f in os.listdir(input_dir) if not f.startswith(".") and not f.startswith("~$")]
        if len(files) == 0:
            raise HTTPException(status_code=400, detail=f"No submission files found in: {input_dir}")


def _ensure_upload_dirs() -> str:
    uploads = "uploads"
    os.makedirs(uploads, exist_ok=True)
    return uploads


def _uploads_question_path() -> str:
    return os.path.join(_ensure_upload_dirs(), "question.txt")


def _uploads_zip_path() -> str:
    return os.path.join(_ensure_upload_dirs(), "submissions.zip")


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
        except OSError:
            pass


@app.post("/rubric/upload")
async def upload_rubric(file: UploadFile = File(...)):
    data = await file.read()
    rubric = _validate_rubric_json_bytes(data)
    _atomic_write_text("rubric.json", json.dumps(rubric, indent=2) + "\n")
    return {"ok": True, "rubric_summary": {"total_marks": rubric["total_marks"], "threshold": rubric["threshold"], "criteria_count": len(rubric["criteria"])}}


@app.post("/rule-engine/update")
async def update_rule_engine(req: UpdateRequest):
    rubric = _load_rubric_from_disk().model_dump()
    new_src = _generate_rule_engine(req.text, rubric)
    _atomic_write_text("rule_engine.py", new_src)
    _validate_runtime()
    return {"ok": True}


@app.post("/prompt-builder/update")
async def update_prompt_builder(req: UpdateRequest):
    rubric = _load_rubric_from_disk().model_dump()
    new_src = _generate_prompt_builder(req.text, rubric)
    _atomic_write_text("prompt_builder.py", new_src)
    _validate_runtime()
    return {"ok": True}


@app.post("/validate")
async def validate_all():
    _validate_runtime(require_inputs=False)
    return {"ok": True}


@app.post("/grade/run")
async def run_grading():
    _validate_runtime(require_inputs=True)
    import importlib
    import sys

    # Ensure valuation picks up the latest prompt_builder/rule_engine.
    importlib.invalidate_caches()
    for name in ("rule_engine", "prompt_builder", "valuation"):
        if name in sys.modules:
            importlib.reload(sys.modules[name])
        else:
            importlib.import_module(name)

    import valuation  # type: ignore
    valuation.main()
    out_path = config.OUTPUT_FILE
    if not os.path.exists(out_path):
        raise HTTPException(status_code=500, detail=f"Expected output file not found: {out_path}")
    return FileResponse(path=out_path, media_type="text/csv", filename="grades.csv")


@app.get("/health")
async def health():
    return JSONResponse({"ok": True})


@app.post("/question/upload")
async def upload_question(req: QuestionUpload):
    _atomic_write_text(_uploads_question_path(), req.question.strip() + "\n")
    return {"ok": True}


@app.post("/moodle/upload-zip")
async def upload_moodle_zip(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Expected a .zip file")
    data = await file.read()
    zip_path = _uploads_zip_path()
    # write as bytes via temp file
    directory = os.path.dirname(os.path.abspath(zip_path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_path, zip_path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
    return {"ok": True, "filename": file.filename}


@app.post("/run/from-question-and-zip")
async def run_from_question_and_zip(req: RunRequest):
    q_path = _uploads_question_path()
    z_path = _uploads_zip_path()
    if not os.path.exists(q_path):
        raise HTTPException(status_code=400, detail="Missing uploaded question. Call POST /question/upload first.")
    if not os.path.exists(z_path):
        raise HTTPException(status_code=400, detail="Missing uploaded ZIP. Call POST /moodle/upload-zip first.")

    question = open(q_path, "r", encoding="utf-8").read().strip()
    if not question:
        raise HTTPException(status_code=400, detail="Uploaded question is empty.")

    # 1) Generate rubric + rule_engine + prompt_builder
    complete = _completion_fn()
    rubric = generator.generate_rubric(
        question_text=question,
        total_marks=req.total_marks,
        threshold=req.threshold,
        complete=complete,
    )
    # Validate rubric schema before writing
    try:
        rubric_valid = Rubric.model_validate(rubric).model_dump()
    except ValidationError as e:
        raise HTTPException(status_code=400, detail={"rubric_validation_error": json.loads(e.json()), "rubric_raw": rubric})

    _atomic_write_text("rubric.json", json.dumps(rubric_valid, indent=2) + "\n")
    _atomic_write_text("rule_engine.py", generator.generate_rule_engine(question, rubric_valid, complete=complete))
    _atomic_write_text("prompt_builder.py", generator.generate_prompt_builder(question, rubric_valid, complete=complete))

    # 2) Prepare inputs from the uploaded ZIP. Keep runs clean.
    _clean_dir_contents(getattr(config, "SUBMISSIONS_DIR", "Submissions"))
    _clean_dir_contents(getattr(config, "FINAL_FILES_DIR", "final_files"))

    import unzip_submissions
    import extract

    submissions_dir = getattr(config, "SUBMISSIONS_DIR", "Submissions")
    extracted_root = os.path.join(submissions_dir, "_uploaded_zip")
    os.makedirs(extracted_root, exist_ok=True)
    rc = unzip_submissions.unzip_to_submissions(z_path, extracted_root, overwrite=True)
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"Unzip failed with code {rc}")

    final_files_dir = getattr(config, "FINAL_FILES_DIR", "final_files")
    rc2 = extract.extract_student_files(source_folder=extracted_root, destination_folder=final_files_dir)
    if rc2 != 0:
        raise HTTPException(status_code=500, detail=f"Extraction failed with code {rc2}")

    # 3) Run grading and return CSV
    _validate_runtime(require_inputs=True)
    import importlib
    import sys

    importlib.invalidate_caches()
    for name in ("rule_engine", "prompt_builder", "valuation"):
        if name in sys.modules:
            importlib.reload(sys.modules[name])
        else:
            importlib.import_module(name)

    import valuation  # type: ignore
    valuation.main()

    out_path = config.OUTPUT_FILE
    if not os.path.exists(out_path):
        raise HTTPException(status_code=500, detail=f"Expected output file not found: {out_path}")
    return FileResponse(path=out_path, media_type="text/csv", filename="grades.csv")
