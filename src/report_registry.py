import pandas as pd


REGISTRY_COLUMNS = ("ticker", "broker", "report_date", "first_seen_at")
KEY_COLUMNS = ["ticker", "broker", "report_date"]


def _normalized_keys(frame):
    result = frame.copy()
    if result.empty:
        return pd.DataFrame(columns=REGISTRY_COLUMNS)
    result["ticker"] = result["ticker"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    result["broker"] = result["broker"].astype(str).str.strip()
    result["report_date"] = pd.to_datetime(result["report_date"], errors="raise").dt.strftime("%Y-%m-%d")
    return result


def update_report_registry(reports, registry, first_seen_at):
    """Preserve the first system-observed timestamp for each immutable report key."""
    existing = _normalized_keys(registry.reindex(columns=REGISTRY_COLUMNS))
    if existing.duplicated(KEY_COLUMNS).any():
        raise ValueError("Ambiguous duplicate report_registry key")
    if not existing.empty and (existing["first_seen_at"].isna() | (existing["first_seen_at"].astype(str).str.strip() == "")).any():
        raise ValueError("report_registry contains missing first_seen_at")

    current = _normalized_keys(reports.loc[:, ["ticker", "broker", "report_date"]])
    if current.duplicated(KEY_COLUMNS).any():
        raise ValueError("Ambiguous duplicate current report key")
    seen = set(map(tuple, existing[KEY_COLUMNS].itertuples(index=False, name=None))) if not existing.empty else set()
    new_rows = []
    for key in current[KEY_COLUMNS].itertuples(index=False, name=None):
        if key not in seen:
            new_rows.append(dict(zip(KEY_COLUMNS, key), first_seen_at=first_seen_at))
            seen.add(key)
    if new_rows:
        existing = pd.concat([existing, pd.DataFrame(new_rows, columns=REGISTRY_COLUMNS)], ignore_index=True)
    return existing.reindex(columns=REGISTRY_COLUMNS).sort_values(KEY_COLUMNS).reset_index(drop=True)
