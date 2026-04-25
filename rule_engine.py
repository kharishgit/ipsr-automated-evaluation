# rule_engine.py

def rule_check(text):
    score = 0

    if "Total" in text:
        score += 10

    if "Average" in text:
        score += 10

    if "NaN" not in text:
        score += 10

    return score