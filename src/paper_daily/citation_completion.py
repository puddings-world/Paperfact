"""Bounded missing-reference continuation inside an already captured AI/job scope."""

import json


def budget(value):
    if type(value) is not int or not 0 <= value <= 2:
        raise ValueError("Additional citation calls must be an integer from 0 to 2")
    return value


def extend(entries, *, prompt, sent, calls, current, complete, decode, answered, log):
    """Keep earlier valid answers; never request paid work after stale input or no progress."""
    budget(calls)
    entries = list(entries)

    def key(entry):
        if not isinstance(entry, dict) or not entry.get("key"):
            return None
        value = str(entry["key"]).strip().strip("[]").strip()
        return str(int(value)) if value.isdigit() else value

    for attempt in range(calls):
        present = {key(entry) for entry in entries if isinstance(entry, dict) and answered(entry)}
        missing = [value for value in sent if value not in present]
        if not missing or not current():
            break
        log(f"Completing missing references: additional call {attempt + 1}/{calls}")
        response, _reason = complete(
            prompt(missing)
            + "\nReturn only valid answers for these missing reference keys: "
            + json.dumps(missing)
        )
        if not response:
            break
        try:
            extra = decode(response)
        except ValueError:
            break
        if not isinstance(extra, list):
            break
        additions = []
        for entry in extra:
            identity = key(entry)
            if identity in missing and isinstance(entry, dict) and answered(entry):
                additions.append(entry)
                missing.remove(identity)
        if not additions:
            break
        entries.extend(additions)
    return entries
