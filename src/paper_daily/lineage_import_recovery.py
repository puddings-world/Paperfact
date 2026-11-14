"""Closed imported Lineage archive data; never receiver/adoption/replay authority."""

from __future__ import annotations

import json

from paper_daily import lineage_package_publish as publisher
from paper_daily import lineage_packages, lineage_sets, local_source_owners, source_snapshots


class ImportRecords:
    def __init__(self):
        self.actions, self.sources, self.reports = {}, {}, {}
        self.size = 0
        self.usages = {}
        self.manifests = {}

    def add(self, name, row):
        if name == publisher.TABLE:
            body = publisher.validate_record(row)
            if row["request_id"] in self.actions:
                raise ValueError("Duplicate Lineage import recovery action")
            self.size += len(row["body_json"].encode())
            if len(self.actions) >= publisher.MAX_ACTIONS or self.size > publisher.MAX_HISTORY:
                raise ValueError("Lineage import recovery history exceeds its budget")
            self.actions[row["request_id"]] = body
        elif name == local_source_owners.TABLE:
            local_source_owners.validate(row)
            if row["request_id"] in self.sources:
                raise ValueError("Duplicate Lineage import original recovery identity")
            self.sources[row["request_id"]] = row

    def finish(self, records):
        if not self.actions:
            return set()
        if len(self.sources) > source_snapshots.MAX_RECEIPTS:
            raise ValueError("Lineage import originals exceed their recovery budget")
        represented = set()
        pairs = {}
        for original in self.sources.values():
            owner = json.loads(original["owner_json"])
            pairs.setdefault((owner["paper_id"], original["sha256"]), original)
        for action in self.actions.values():
            for item in action["records"]:
                row = json.loads(item["row_json"])
                for original in item["sources"]:
                    if self.sources.get(original["request_id"]) != original:
                        raise ValueError(
                            "Lineage import recovery lacks its exact original association"
                        )
                    if records.refs.get(original["sha256"]) != original["size"]:
                        raise ValueError("Lineage import recovery lacks its exact original bytes")
                encoded = lineage_packages._json(row)
                represented.add(encoded)
                self.reports[encoded] = row
                before = json.loads(item["before_json"])
                if before is not None:
                    self.reports[lineage_packages._json(before)] = before
        # Historical data may refer to retired owners; no current lifetime is
        # inferred from these rows. Canonical owners retain the outer validation.
        for row in self.reports.values():
            body = lineage_sets.decode(row["body_json"])
            for binding, source in zip(body["bindings"], body["report"]["sources"], strict=True):
                if source["availability"] == "unavailable":
                    continue
                original = pairs.get((binding["paper_id"], source["document_hash"]))
                if original is None or records.refs.get(original["sha256"]) != original["size"]:
                    raise ValueError(
                        "Displaced Lineage original lacks its retained paper/source provenance"
                    )
                digest = original["sha256"]
                self.manifests[digest] = {k: original[k] for k in ("sha256", "size", "media_type")}
                self.usages.setdefault(digest, []).append((body["report"], source))
        return represented

    def verify(self, read):
        """Independently verify saved located quotes/pages against actual archive bytes."""
        for digest, usages in self.usages.items():
            descriptor = self.manifests[digest]
            data = read(descriptor)
            if len(data) != descriptor["size"]:
                raise ValueError("Lineage recovery original differs from its declared size")
            lineage_packages.verify_original(data, digest, usages)
