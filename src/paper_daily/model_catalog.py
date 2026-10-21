"""Account-scoped public model names; routing IDs remain unchanged."""

from threading import RLock

_catalogs = {}
_lock = RLock()


def key(cfg):
    return cfg.backend, cfg.account_id or "local", cfg.cli_home or "", cfg.base_url or ""


def remember(cfg, rows):
    names = {}
    default = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        value, label = row.get("value"), row.get("displayName")
        if isinstance(value, str) and isinstance(label, str) and 0 < len(label) < 160:
            names[value] = label
        if value == "default":
            default = row
    # Resolve the descriptive default only when it matches a returned model name.
    description = default.get("description", "") if default else ""
    candidate = description.split("·", 1)[0].strip() if isinstance(description, str) else ""
    names[""] = candidate if candidate in {v for k, v in names.items() if k != "default"} else ""
    with _lock:
        _catalogs[key(cfg)] = names


def name(cfg, model):
    with _lock:
        return _catalogs.get(key(cfg), {}).get(model or "") or None


def models(cfg):
    """Last observed public model IDs, for immediate display during refresh."""
    with _lock:
        return [model for model in _catalogs.get(key(cfg), {}) if model not in ("", "default")]
