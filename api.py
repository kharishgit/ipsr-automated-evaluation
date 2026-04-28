import ast
import json
import os
import tempfile
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError

from openai import OpenAI

import config


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
    if not config.DEEPSEEK_API_KEY:
        raise HTTPException(status_code=500, detail="Missing DEEPSEEK_API_KEY in environment/.env")
    return OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.BASE_URL,
        default_headers={
            "HTTP-Referer": "http://localhost",
            "X-Title": "ipsr-grading-api",
        },
    )


def _extract_code_block(text: str) -> str:
    # Accept raw Python or fenced code; return best-effort extracted python.
    if "```" not in text:
        return text.strip()
    parts = text.split("```")
    if len(parts) < 3:
        return text.strip()
    # Prefer the first fenced block body
    block = parts[1]
    lines = block.splitlines()
    if lines and lines[0].strip().lower() in {"python", "py"}:
        lines = lines[1:]
    return "\n".join(lines).strip()


def _assert_safe_function_source(src: str, fn_name: str) -> ast.FunctionDef:
    try:
        mod = ast.parse(src)
    except SyntaxError as e:
        raise HTTPException(status_code=400, detail=f"Generated code has syntax error: {e}")

    banned_names = {
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "os",
        "sys",
        "subprocess",
        "shutil",
        "pathlib",
        "socket",
    }

    for node in ast.walk(mod):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise HTTPException(status_code=400, detail="Generated code must not contain imports")
        if isinstance(node, ast.Global):
            raise HTTPException(status_code=400, detail="Generated code must not use global")
        if isinstance(node, ast.Nonlocal):
            raise HTTPException(status_code=400, detail="Generated code must not use nonlocal")
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in banned_names:
            raise HTTPException(status_code=400, detail=f"Generated code uses banned name: {node.id}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in banned_names:
            raise HTTPException(status_code=400, detail=f"Generated code calls banned function: {node.func.id}")

    allowed_prelude = []
    for n in mod.body:
        # Allow a module docstring; comments are not in the AST.
        if isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant) and isinstance(n.value.value, str):
            allowed_prelude.append(n)
            continue
        if isinstance(n, ast.FunctionDef):
            continue
        raise HTTPException(status_code=400, detail="Generated code must not contain top-level statements other than the function")

    fns = [n for n in mod.body if isinstance(n, ast.FunctionDef)]
    if len(fns) != 1 or fns[0].name != fn_name:
        raise HTTPException(status_code=400, detail=f"Generated code must define exactly one function: {fn_name}()")
    return fns[0]


def _generate_rule_engine(text: str, rubric: dict[str, Any]) -> str:
    client = _llm_client()
    system = (
        "You update a Python grading rule function.\n"
        "Return ONLY Python source code defining exactly one function:\n"
        "def rule_check(text: str) -> int:\n"
        "No imports. No file/network access. No side effects.\n"
        "Score should be an integer between 0 and 30.\n"
    )
    user = (
        "Rubric JSON:\n"
        f"{json.dumps(rubric, indent=2)}\n\n"
        "Instruction from user:\n"
        f"{text}\n\n"
        "Return the function now."
    )
    resp = client.chat.completions.create(
        model=config.MODEL,
        temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    content = resp.choices[0].message.content or ""
    code = _extract_code_block(content)
    _assert_safe_function_source(code, "rule_check")
    return "# rule_engine.py\n\n" + code.strip() + "\n"


def _generate_prompt_builder(text: str, rubric: dict[str, Any]) -> str:
    client = _llm_client()
    system = (
        "You update a Python prompt builder for LLM grading.\n"
        "Return ONLY Python source code defining exactly one function:\n"
        'def build_prompt(rubric: dict, student_text: str, mode: str = "lenient") -> str:\n'
        "No imports. No file/network access.\n"
    )
    user = (
        "Current rubric JSON:\n"
        f"{json.dumps(rubric, indent=2)}\n\n"
        "Instruction from user:\n"
        f"{text}\n\n"
        "The function should produce a prompt that forces the model to return ONLY valid JSON.\n"
        "Return the function now."
    )
    resp = client.chat.completions.create(
        model=config.MODEL,
        temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    content = resp.choices[0].message.content or ""
    code = _extract_code_block(content)
    _assert_safe_function_source(code, "build_prompt")
    # Keep existing import for compatibility with old code that does json.dumps in the function.
    return "import json\n\n# prompt_builder.py\n\n" + code.strip() + "\n"


def _validate_runtime() -> None:
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
    input_dir = config.INPUT_FOLDER
    if not os.path.isdir(input_dir):
        raise HTTPException(status_code=400, detail=f"Missing input folder: {input_dir}")
    files = [f for f in os.listdir(input_dir) if not f.startswith(".") and not f.startswith("~$")]
    if len(files) == 0:
        raise HTTPException(status_code=400, detail=f"No submission files found in: {input_dir}")


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
    _validate_runtime()
    return {"ok": True}


@app.post("/grade/run")
async def run_grading():
    _validate_runtime()
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
