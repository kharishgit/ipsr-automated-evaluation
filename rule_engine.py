# rule_engine.py

def rule_check(text):
    score = 0
    text_lower = text.lower()

    # Dashboard indicators
    if "dashboard" in text_lower:
        score += 10

    # Common analysis keywords
    keywords = [
        "product", "city", "category",
        "sales", "trend", "month",
        "rep", "total"
    ]

    for word in keywords:
        if word in text_lower:
            score += 2  # small boost per keyword

    # Insight indicators
    insight_words = [
        "highest", "lowest", "increase",
        "decrease", "trend", "comparison"
    ]

    for word in insight_words:
        if word in text_lower:
            score += 3

    # Avoid NaN / broken data
    if "nan" not in text_lower:
        score += 5

    if "slicer" in text.lower():
        score += 10

    if "sheet" in text.lower():
        score += 5

    return min(score, 30)  # cap rule score