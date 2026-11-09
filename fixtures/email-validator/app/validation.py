def is_valid_email(value: str) -> bool:
    """Return whether a value looks like an email address."""
    return "@" in value
