import ast
import json
from typing import Any, Callable


def extract_code_block(text: str) -> str:
    if "```" not in text:
        return text.strip()
    parts = text.split("```")
    if len(parts) < 3:
        return text.strip()
    block = parts[1]
    lines = block.splitlines()
    if lines and lines[0].strip().lower() in {"python", "py"}:
        lines = lines[1:]
    return "\n".join(lines).strip()


def assert_safe_function_source(src: str, fn_name: str) -> ast.FunctionDef:
    mod = ast.parse(src)

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
            raise ValueError("Generated code must not contain imports")
        if isinstance(node, ast.Global):
            raise ValueError("Generated code must not use global")
        if isinstance(node, ast.Nonlocal):
            raise ValueError("Generated code must not use nonlocal")
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in banned_names:
            raise ValueError(f"Generated code uses banned name: {node.id}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in banned_names:
            raise ValueError(f"Generated code calls banned function: {node.func.id}")

    for n in mod.body:
        if isinstance(n, ast.FunctionDef):
            continue
        if isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant) and isinstance(n.value.value, str):
            continue
        raise ValueError("Generated code must not contain top-level statements other than the function")

    fns = [n for n in mod.body if isinstance(n, ast.FunctionDef)]
    if len(fns) != 1 or fns[0].name != fn_name:
        raise ValueError(f"Generated code must define exactly one function: {fn_name}()")
    return fns[0]


def generate_rubric(
    question_text: str,
    total_marks: int,
    threshold: int,
    complete: Callable[[str, str], str],
) -> dict[str, Any]:
    system = (
        "You design grading rubrics for spreadsheet/data-analysis assignments.\n"
        "Return ONLY valid JSON matching this schema:\n"
        '{ "total_marks": int, "threshold": int, "criteria": [ { "name": str, "marks": int, "description": str } ], "instructions": str }\n'
        "Rules:\n"
        f"- total_marks must be exactly {total_marks}\n"
        f"- threshold must be exactly {threshold}\n"
        "- criteria marks must sum to total_marks\n"
        "- Use 6 to 12 criteria\n"
        "- Keep criterion names short and specific\n"
        "- Do not include markdown or commentary\n"
    )
    user = f"Assignment question:\n{question_text}\n\nReturn the rubric JSON now."
    content = complete(system, user).strip()
    try:
        return json.loads(content)
    except Exception:
        # best-effort: extract a JSON object from mixed output
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(content[start : end + 1])
        raise


def generate_rule_engine(
    question_text: str,
    rubric: dict[str, Any],
    complete: Callable[[str, str], str],
) -> str:
    system = (
        "You write a Python function that gives a quick heuristic score from extracted submission text.\n"
        "Return ONLY Python source defining exactly one function:\n"
        "def rule_check(text: str) -> int:\n"
        "No imports. No I/O. No side effects.\n"
        "Score must be an integer between 0 and 30.\n"
    )
    user = (
        "Assignment question:\n"
        f"{question_text}\n\n"
        "Rubric JSON:\n"
        f"{json.dumps(rubric, indent=2)}\n\n"
        "Return the function now."
    )
    content = complete(system, user)
    code = extract_code_block(content)
    assert_safe_function_source(code, "rule_check")
    return "# rule_engine.py\n\n" + code.strip() + "\n"


def generate_prompt_builder(
    question_text: str,
    rubric: dict[str, Any],
    complete: Callable[[str, str], str],
) -> str:
    system = (
        "You write a Python function that builds a grading prompt for an LLM.\n"
        "Return ONLY Python source defining exactly one function:\n"
        'def build_prompt(rubric: dict, student_text: str, mode: str = "lenient") -> str:\n'
        "No imports. No I/O.\n"
        "The prompt must force the model to return ONLY valid JSON of the form:\n"
        '{"marks": number, "reason": "string"}\n'
    )
    user = (
        "Assignment question:\n"
        f"{question_text}\n\n"
        "Rubric JSON:\n"
        f"{json.dumps(rubric, indent=2)}\n\n"
        "Return the function now."
    )
    content = complete(system, user)
    code = extract_code_block(content)
    assert_safe_function_source(code, "build_prompt")
    return "import json\n\n# prompt_builder.py\n\n" + code.strip() + "\n"
