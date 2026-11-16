"""Bounded read-only checks of a saved list report's owned originals and locations."""

import hmac
import json
import math
import secrets
import time
from dataclasses import dataclass, field

from paper_daily import survey_reader

FORMAT = "paperfact.survey-audit.v1"
MAX_ORIGINALS = 16
MAX_BYTES = 128 * 1024**2


_KEY = secrets.token_bytes(32)


def _signature(saved, result_json, observations):
    value = repr((id(saved), result_json, tuple(id(item) for item in observations))).encode()
    return hmac.digest(_KEY, value, "sha256")


@dataclass(frozen=True, slots=True)
class PreparedSurveyAudit:
    """Read-only delivery witness; neither a file grant nor a scientific verdict."""

    _saved: survey_reader.SavedReport = field(repr=False)
    _json: str = field(repr=False)
    _observations: tuple = field(repr=False)
    _seal: bytes = field(repr=False)

    def current(self):
        try:
            return (hmac.compare_digest(self._seal,
                        _signature(self._saved, self._json, self._observations))
                    and self._saved.current()
                    and all(current() for current in self._observations)
                    and self._saved.current())
        except (ValueError, TypeError, OSError):
            return False

    def for_delivery(self, saved):
        if saved is not self._saved or not self.current():
            raise survey_reader.ReadChanged("Saved report/original changed before audit delivery")
        return json.loads(self._json)


def audit(saved, *, cancelled=lambda: False, seconds=60):
    """Synchronous JSON API; desktop callers retain prepare() through queued delivery."""
    return prepare(saved, cancelled=cancelled, seconds=seconds).for_delivery(saved)


def prepare(saved, *, cancelled=lambda: False, seconds=60):
    """Check each source once and retain metadata-only observations through delivery."""
    if (not isinstance(saved, survey_reader.SavedReport) or not saved.current()
            or type(seconds) not in (int, float) or not math.isfinite(seconds)
            or not 0 < seconds <= 120):
        raise ValueError("Refresh a saved report and use a bounded audit budget")
    data = saved.data
    if data["kind"] == "none":
        raise ValueError("No source-aware report is saved for this list")
    report = data["report"]
    captured = [source for source in report["sources"] if source["state"] == "captured"]
    if len(captured) > MAX_ORIGINALS:
        raise ValueError("Selected report exceeds the 16-original audit budget")
    deadline = time.monotonic() + seconds

    def stopped():
        return cancelled() or time.monotonic() >= deadline

    def check():
        survey_reader._cancel(stopped)
        if not saved.current():
            raise survey_reader.ReadChanged("Saved report changed during source audit")

    bindings = {row["source_id"]: row for row in data["sources"]}
    observations, findings, used, verified = [], [], 0, 0
    for source in report["sources"]:
        check()
        state = source["state"]
        if state == "captured":
            binding = bindings.get(source["id"])
            if binding is None:
                state = "unavailable"
            else:
                try:
                    raw, fresh = survey_reader._checked_original(saved, source, binding, stopped)
                    used += len(raw)
                    del raw
                except (OSError, ValueError):
                    check()  # Cancellation/stale capture is not an unavailable-source finding.
                    state = "unavailable"
                else:
                    if used > MAX_BYTES:
                        raise ValueError("Selected report exceeds the original-byte audit budget")
                    observations.append(fresh)
                    state = "verified"
                    verified += 1
        findings.append(dict(source_id=source["id"], state=state))
    check()
    statements = [item for section in report["sections"] for item in section["statements"]]
    passages = [passage for item in statements for passage in item["passages"]]
    located = sum(bool(p["location"] and p["location"]["state"] == "located")
                  for p in passages)
    verified_ids = {row["source_id"] for row in findings if row["state"] == "verified"}
    result = dict(format=FORMAT, list_id=data["list_id"], report_id=report["id"],
                report_kind=data["kind"], update_pending=data["update_pending"],
                originals_total=len(captured), originals_verified=verified,
                verified_bytes=used, sources=findings, statements=len(statements),
                statements_without_passages=sum(not item["passages"] for item in statements),
                recorded_located_passages=located, unlocated_passages=len(passages)-located,
                verified_located_passages=sum(bool(p["location"]
                    and p["location"]["state"] == "located"
                    and p["source_id"] in verified_ids) for p in passages),
                semantics="not_checked")
    encoded = json.dumps(result, separators=(",", ":"), allow_nan=False)
    observations = tuple(observations)
    prepared = PreparedSurveyAudit(saved, encoded, observations,
                                   _signature(saved, encoded, observations))
    prepared.for_delivery(saved)
    return prepared
