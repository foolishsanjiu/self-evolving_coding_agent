def user_label(name: str) -> str:
    normalized = " ".join(name.strip().split()).title()
    return f"User: {normalized}"


def admin_label(name: str) -> str:
    normalized = " ".join(name.strip().split()).title()
    return f"Admin: {normalized}"
