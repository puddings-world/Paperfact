"""Process-local, resumable verification of selected current offline attachments.

Proofs remain native sealed objects. No persisted flag or imported report is trusted.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from copy import deepcopy

from paper_daily import workspace_offline as offline
from paper_daily.workspace_service import SnapshotChanged, Ticket

MAX_PASS_BYTES = 256 * 1024**2
MAX_CACHED_ASSETS = 4096
MAX_SELECTION_BYTES = 8 * 1024**3


class OfflineVerification:
    def __init__(self, service, paper_ids, *, ticket=None):
        if not isinstance(service, offline.OfflineService):
            raise ValueError("An explicit offline workspace service is required")
        self.service = service
        self.selection = tuple(offline._selection(paper_ids))
        self._initial = deepcopy(service.plan(list(self.selection), ticket)["papers"])
        self._proofs = {}
        self._running = threading.Lock()
        self._pass = 0

    @staticmethod
    def _key(target):
        return hashlib.sha256(
            json.dumps(target, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _live(self, ticket):
        self.service._check(ticket)
        if self.service._snapshot(self.selection, ticket) != self._initial:
            self._proofs.clear()
            raise SnapshotChanged("Selected research changed; start a new verification")

    def advance(
        self,
        ticket=None,
        *,
        max_bytes=MAX_PASS_BYTES,
        max_assets=offline.MAX_ASSETS,
        seconds=10,
        progress=lambda _event: None,
    ):
        """Resume native proofs; each return rechecks source and file-version observations."""
        if (
            type(max_bytes) is not int
            or not 0 < max_bytes <= MAX_PASS_BYTES
            or type(max_assets) is not int
            or not 0 < max_assets <= offline.MAX_ASSETS
            or isinstance(seconds, bool)
            or not isinstance(seconds, (float, int))
            or not 0 < seconds <= 30
        ):
            raise ValueError("Invalid offline verification pass budget")
        if not self._running.acquire(blocking=False):
            raise RuntimeError("Offline verification is already running")
        try:
            return self._advance(ticket or Ticket(), max_bytes, max_assets, seconds, progress)
        finally:
            self._running.release()

    def _advance(self, ticket, max_bytes, max_assets, seconds, progress):
        self._live(ticket)
        report = self.service.plan(list(self.selection), ticket)
        if (
            report["required_assets"] > MAX_CACHED_ASSETS
            or report["required_bytes"] > MAX_SELECTION_BYTES
        ):
            raise ValueError("Selected verification exceeds its retained-proof limit")
        store = self.service._store()
        deadline = time.monotonic() + seconds
        spent = checked = reused = 0
        proofs = []
        self._pass += 1
        for paper in report["papers"]:
            entries = [(paper["pdf"], True), *[(item, False) for item in paper["artifacts"]]]
            for item, is_pdf in entries:
                self.service._check(ticket)
                if item["state"] != "unchecked":
                    continue
                if store is None:
                    item["state"] = "unconfigured"
                    continue
                target = item["target"] if is_pdf else item["operation"]
                rows = [item["target"]] if is_pdf else offline.referenced_blobs(target)
                key = self._key(target)
                cached = self._proofs.get(key)
                if cached is not None and cached.matches(target):
                    proof = cached
                    reused += len(rows)
                else:
                    self._proofs.pop(key, None)
                    size, count = sum(row["size"] for row in rows), len(rows)
                    if (
                        spent + size > max_bytes
                        or checked + count > max_assets
                        or time.monotonic() >= deadline
                    ):
                        item["state"] = "budget_exceeded"
                        continue
                    spent, checked = spent + size, checked + count
                    try:
                        if is_pdf:
                            proof = offline.verify_document(store, target)
                        else:
                            proof, _body, _blobs = offline.verify_closure(store, target)
                    except (OSError, ValueError):
                        item["state"] = "unavailable"
                        continue
                    self.service._check(ticket)
                    if not proof.matches(target):
                        item["state"] = "invalid"
                        continue
                    self._proofs[key] = proof
                    if time.monotonic() >= deadline:
                        item["state"] = "budget_exceeded"
                        continue
                item["state"] = "verified"
                proofs.append((item, proof, deepcopy(target), deepcopy(rows), key))
                current_assets = {
                    row["sha256"]
                    for entry, _proof, _target, refs, _key in proofs
                    if entry["state"] == "verified"
                    for row in refs
                }
                progress(
                    {
                        "stage": "verification",
                        "verified_assets": len(current_assets),
                        "required_assets": report["required_assets"],
                        "checked_assets": checked,
                        "reused_assets": reused,
                        "verification_bytes": spent,
                    }
                )
        self._live(ticket)
        self.service._store()
        for item, proof, target, _rows, key in proofs:
            if not proof.matches(target):
                item["state"] = "invalid"
                self._proofs.pop(key, None)
        for paper in report["papers"]:
            paper["ready"] = (
                paper["pdf"]["state"] == "verified"
                and paper["artifact_inventory_available"]
                and all(
                    item["state"] == "verified" and item["source_state"] in {"current", "original"}
                    for item in paper["artifacts"]
                )
            )
        verified = {
            row["sha256"]: row["size"]
            for item, _proof, _target, rows, _key in proofs
            if item["state"] == "verified"
            for row in rows
        }
        report.update(
            ready=bool(report["papers"]) and all(paper["ready"] for paper in report["papers"]),
            partial=any(
                item["state"] == "budget_exceeded"
                for paper in report["papers"]
                for item in [paper["pdf"], *paper["artifacts"]]
            ),
            verified_bytes=sum(verified.values()),
            verified_assets=len(verified),
            verification_bytes=spent,
            checked_assets=checked,
            reused_assets=reused,
            verification_pass=self._pass,
            resumable=True,
        )
        return report
