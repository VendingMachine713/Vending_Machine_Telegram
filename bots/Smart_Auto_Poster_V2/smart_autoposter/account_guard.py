from __future__ import annotations


def duplicate_authorized_account_ids(auth: dict[str, dict]) -> list[tuple[str, str, int]]:
    """Return account-key pairs that are authorized as the same Telegram user."""
    seen: dict[int, str] = {}
    duplicates: list[tuple[str, str, int]] = []
    for key, state in auth.items():
        if not state or not state.get("authorized"):
            continue
        user_id = state.get("user_id")
        if user_id in (None, ""):
            continue
        user_id = int(user_id)
        if user_id in seen:
            duplicates.append((seen[user_id], key, user_id))
        else:
            seen[user_id] = key
    return duplicates


def assert_distinct_authorized_accounts(auth: dict[str, dict]) -> None:
    duplicates = duplicate_authorized_account_ids(auth)
    if not duplicates:
        return
    pairs = ", ".join(f"{a}/{b} -> Telegram user {uid}" for a, b, uid in duplicates)
    raise RuntimeError(
        "Duplicate Telegram account sessions detected: " + pairs + ". "
        "Primary and Secondary must authenticate as different Telegram users. "
        "Re-login the affected session before scanning or starting the service."
    )
