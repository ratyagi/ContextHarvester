def count_tokens(text: str) -> int:
    """Approximate token count (~4 chars/token). One place, so budgets stay consistent."""
    return max(1, len(text) // 4)
