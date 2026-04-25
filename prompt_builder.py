# prompt_builder.py
import json

def build_prompt(rubric, student_text, mode="lenient"):
    
    if mode == "lenient":
        instruction = """
- Focus on insights and observations
- Ignore grammar and formatting mistakes
- Reward correct understanding of data
- Be slightly lenient
"""
    else:
        instruction = """
- Strictly check data correctness
- Penalize wrong calculations
- Ensure proper structure
- Do not be lenient
"""

    return f"""
You are a generous grading system.

Instructions:
{instruction}

IMPORTANT:
- Return ONLY valid JSON
- Do NOT include explanations or markdown
- Output must start with {{ and end with }}

- If summary metrics like Total Sales, Average, Count are present, consider calculations as done
- Do NOT assume functions are missing just because formulas are not visible

Rubric:
{json.dumps(rubric, indent=2)}

Student Submission:
{student_text}

Output format:
{{"marks": number, "reason": "ONLY if marks < {rubric['threshold']}, else empty"}}
"""