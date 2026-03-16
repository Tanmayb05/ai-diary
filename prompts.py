PROMPTS = [
    "What made you smile today?",
    "What was the hardest moment today?",
    "What did you learn today?",
    "What are you grateful for today?",
]


MOODS = {
    "great": "😄 Great",
    "good": "🙂 Good",
    "neutral": "😐 Neutral",
    "bad": "😔 Bad",
}


def list_prompts() -> list[str]:
    return PROMPTS.copy()


def mood_choices() -> dict[str, str]:
    return MOODS.copy()
