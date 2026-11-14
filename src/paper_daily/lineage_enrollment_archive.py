"""Archived unbound Lineage closure after explicit fresh workspace enrollment.

Old receipts remain data. Validate their historical graph and exact originals
separately from the new workspace; never install old identities as runtime grants.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from paper_daily import lineage_packages, lineage_recovery, lineage_sets

PROTOCOLS = {
    "research_lineage_publications",
    "research_lineage_imports",
    "research_lineage_actions",
    "research_generation_requests",
    "research_generation_recovery",
}


class Records:
    def __init__(self):
        self.history = []
        self.sources = []
        self.lineage = None

    def add_history(self, protocol, row):
        if protocol not in PROTOCOLS:
            return
        if (
            protocol.startswith("research_generation_")
            and json.loads(row["context_json"]).get("format")
            != "paperfact.lineage-proposal-context.v1"
        ):
            return
        self.history.append((protocol, row))

    def add_source(self, row):
        self.sources.append(row)

    def finish(self, records):
        if not self.history:
            return
        lineage = lineage_recovery.Records()
        for protocol, row in self.history:
            lineage.add(protocol, row)
        needed, pairs = set(), set()
        rows = []
        for receipt in lineage.publications.values():
            row, sources = lineage_recovery.publication(receipt)
            rows.append(row)
            needed.update(source["request_id"] for source in sources)
        for action in lineage.imported.actions.values():
            for item in action["records"]:
                rows.append(json.loads(item["row_json"]))
                before = json.loads(item["before_json"])
                if before is not None:
                    rows.append(before)
                needed.update(source["request_id"] for source in item["sources"])
        for row in rows:
            body = lineage_sets.decode(row["body_json"])
            for binding, source in zip(body["bindings"], body["report"]["sources"], strict=True):
                if source["availability"] == "available":
                    pairs.add((binding["paper_id"], source["document_hash"]))
        for source in self.sources:
            owner = json.loads(source["owner_json"])
            if source["request_id"] in needed or (owner.get("paper_id"), source["sha256"]) in pairs:
                lineage.add("research_local_source_owners", source)
        lineage.finish(
            SimpleNamespace(
                workspace=None,
                paper_ids=records.paper_ids,
                paper_map={},
                refs=records.refs,
            )
        )
        self.lineage = lineage

    def verify(self, read):
        if self.lineage is None:
            return
        self.lineage.imported.verify(read)
        usages, manifests = {}, {}
        for receipt in self.lineage.publications.values():
            row, originals = lineage_recovery.publication(receipt)
            body = lineage_sets.decode(row["body_json"])
            for source in body["report"]["sources"]:
                if source["availability"] != "available":
                    continue
                digest = source["document_hash"]
                original = next(item for item in originals if item["sha256"] == digest)
                manifests[digest] = {key: original[key] for key in ("sha256", "size", "media_type")}
                usages.setdefault(digest, []).append((body["report"], source))
        for digest, selected in usages.items():
            lineage_packages.verify_original(read(manifests[digest]), digest, selected)
