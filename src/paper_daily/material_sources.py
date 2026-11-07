"""Process-only material selections and independently owned original-PDF reads.

All collection/ownership/PDF work belongs on a worker. GUI selection and admission
use bounded frozen item metadata/native witnesses only. No capability is part of
Materials, a MIME payload, scientific serialization, a deck or a claim record.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from contextlib import closing
from itertools import islice
from pathlib import Path
from types import MappingProxyType

import pymupdf

from paper_daily import active_deck_originals as reads
from paper_daily import local_deck_proposals as catalog
from paper_daily import local_source_owners, source_snapshots
from paper_daily.document_reader import DocumentReader, ResolvedDocument
from paper_daily.enrolled_deck_proposals import _runtime, _target
from paper_daily.materials import Materials
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_artifacts import desired_file, paper_current
from paper_daily.sync_deck_publication import runtime
from paper_daily.sync_documents import MAX_PDF_BYTES
from paper_daily.sync_files import canonical_json, file_id, validate_closure
from paper_daily.workspace_service import _ReadOnlyStore

MAX_ITEMS = 1024
MAX_ITEM_BYTES = 64 * 1024
MAX_COLLECTION_BYTES = 8 * 1024**2
_SEAL = object()


class OriginalUnavailable(ValueError):
    """Scientific content is preserved, but no independent historical read is granted."""


class _ProcessObject:
    __slots__ = ("_values", "_seal")

    def __setattr__(self, *_args):
        raise AttributeError("Material source observations are immutable")

    def __reduce__(self):
        raise TypeError("Material source capabilities are process-only")

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None


def _make(cls, **values):
    result = object.__new__(cls)
    object.__setattr__(result, "_values", MappingProxyType(values))
    object.__setattr__(result, "_seal", _SEAL)
    return result


def _sealed(value, cls):
    if not isinstance(value, cls) or value._seal is not _SEAL:
        raise ValueError("Use an actual material source observation")


def _freeze(value, budget=None, depth=0):
    budget = [8192] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0 or depth > 12:
        raise ValueError("Material item exceeds its structural bound")
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("Material keys must be strings")
        return MappingProxyType(
            {key: _freeze(child, budget, depth + 1) for key, child in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child, budget, depth + 1) for child in value)
    if value is None or type(value) in (str, bool, int):
        if isinstance(value, str) and len(value) > MAX_ITEM_BYTES:
            raise ValueError("Material text exceeds its bound")
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("Material payload requires finite plain metadata")


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain(child) for child in value]
    return value


class MaterialItem(_ProcessObject):
    __slots__ = ()

    @property
    def payload(self):
        return _plain(self._payload)


def project_items(materials):
    """Worker: exactly the existing Panel scientific payload schema, including tables.

    group/index/variant identify a tree position. key additionally binds its full
    bounded payload; it is an item key, never paper/source ownership authority.
    """
    if not isinstance(materials, Materials):
        raise ValueError("Use an actual collected Materials result")
    groups = (materials.exhibits, materials.headings, materials.sentences)
    if any(
        type(group) is not list or any(type(item) is not dict for item in group) for group in groups
    ):
        raise ValueError("Material groups require plain item lists")
    result, total = [], 0

    def append(group, index, payload, variant="main"):
        nonlocal total
        frozen = _freeze(payload)
        encoded = canonical_json(_plain(frozen))
        total += len(encoded)
        if (
            len(encoded) > MAX_ITEM_BYTES
            or total > MAX_COLLECTION_BYTES
            or len(result) >= MAX_ITEMS
        ):
            raise ValueError("Material collection exceeds its item/byte bound; nothing truncated")
        key = f"{group}:{index}:{variant}:" + hashlib.sha256(encoded).hexdigest()
        result.append(
            _make(MaterialItem, group=group, index=index, variant=variant, key=key, _payload=frozen)
        )

    for index, item in enumerate(materials.exhibits):
        append(
            "exhibits",
            index,
            dict(
                kind="exhibit",
                **{
                    key: item.get(key)
                    for key in (
                        "id",
                        "file",
                        "label",
                        "caption",
                        "page",
                        "rows",
                        "rect",
                        "document_hash",
                        "cache_key",
                        "navigation_available",
                        "navigation_reason",
                    )
                },
            ),
        )
        if item.get("rows"):
            append(
                "exhibits",
                index,
                dict(
                    kind="table",
                    id=item["id"],
                    label=item["label"],
                    page=item.get("page"),
                    rect=item.get("rect"),
                    document_hash=item.get("document_hash"),
                    rows=item["rows"],
                ),
                "table",
            )
    for index, item in enumerate(materials.headings):
        append("headings", index, dict(item, kind="heading"))
    for index, item in enumerate(materials.sentences):
        append(
            "sentences",
            index,
            dict(
                kind="sentence",
                text=item["text"],
                page=item.get("page"),
                source=item.get("source"),
                reason=item.get("reason", ""),
                anchor=item.get("anchor"),
                mark_id=item.get("mark_id"),
                origin=item.get("origin", "ai"),
                document_hash=item.get("document_hash"),
                navigation_available=item.get("navigation_available"),
                navigation_reason=item.get("navigation_reason"),
            ),
        )
    return tuple(result)


class Collection(_ProcessObject):
    __slots__ = ()

    def item(self, group, index, variant="main"):
        return next(
            (
                item
                for item in self.items
                if (item.group, item.index, item.variant) == (group, index, variant)
            ),
            None,
        )


class Selection(_ProcessObject):
    __slots__ = ()

    @property
    def payload(self):
        return self.item.payload


class OriginalProof(_ProcessObject):
    __slots__ = ()

    @property
    def source(self):
        return _plain(self._source)


def _receipt_sources(conn, database, native, paper_id, epoch, sha, files, current):
    """Only the known native/null-binding namespace and bounded selected SQL rows."""
    rows = [(row, None, None) for row in local_source_owners.records(conn, document_hash=sha)]
    root = (
        database.parent
        / ".paperfact-source-snapshots"
        / source_snapshots._namespace(dict(database_identity=list(native), binding=None))
    )
    if root.exists():
        root = catalog._path(root)
        entries = list(islice(root.iterdir(), source_snapshots.MAX_RECEIPTS * 2 + 1))
        if len(entries) > source_snapshots.MAX_RECEIPTS * 2:
            raise ValueError("Original receipt namespace exceeds its entry bound")
        total = 0
        for entry in sorted(entries):
            catalog._path(entry)
            if entry.is_dir():
                from paper_daily.position_source_snapshots import is_stage

                if is_stage(entry):
                    continue
            receipt = entry / "receipt.json" if entry.is_dir() else entry
            size = receipt.stat().st_size
            total += size
            if (
                not 0 < size <= source_snapshots.MAX_RECEIPT
                or total > local_source_owners.MAX_METADATA
            ):
                raise ValueError("Original receipt namespace exceeds its byte bound")
            scan_files = {}
            encoded = reads._read(receipt, size, scan_files, current)
            row = source_snapshots.validate(
                source_snapshots._decode(encoded), max_pdf_bytes=MAX_PDF_BYTES
            )
            if source_snapshots.receipt_path(database, row) != catalog._path(receipt):
                raise ValueError("Original receipt has another native location")
            if row["sha256"] == sha:
                rows.append((row, str(receipt), scan_files[str(catalog._path(receipt))]))
    found = []
    for row, receipt, version in rows:
        owner = json.loads(row["owner_json"])
        if (
            owner["database_identity"] == list(native)
            and owner["binding"] is None
            and owner["paper_id"] == owner["source_owner_id"] == paper_id
            and owner["parent_lifecycle"] == epoch
        ):
            if receipt is not None:
                files[str(catalog._path(receipt))] = version
            path = source_snapshots.source_path(database, row, max_pdf_bytes=MAX_PDF_BYTES)
            found.append(
                dict(
                    kind="receipt",
                    record=row,
                    receipt=receipt,
                    path=str(catalog._path(path)),
                    descriptor={key: row[key] for key in ("sha256", "size", "media_type")},
                )
            )
    return found


def _local_sources(conn, database, native, paper_id, epoch, sha, files, current):
    result = _receipt_sources(conn, database, native, paper_id, epoch, sha, files, current)
    if catalog._schema(conn):
        ids = conn.execute(
            "SELECT proposal_id FROM "
            + catalog.TABLE
            + " WHERE paper_id=? ORDER BY proposal_id LIMIT ?",
            (paper_id, catalog.MAX_RECORDS + 1),
        ).fetchall()
        if len(ids) > catalog.MAX_RECORDS:
            raise ValueError("Local original catalog exceeds its row bound")
        total = 0
        for identity in ids:
            row = catalog.record(conn, identity[0])
            total += len(canonical_json(row))
            if total > catalog.MAX_CATALOG_BYTES:
                raise ValueError("Local original catalog exceeds its byte bound")
            owner = json.loads(row["owner_json"])
            if owner["parent_token"] != epoch:
                continue
            catalog._scope(conn, owner, exact_row=False)
            if owner["database"] != str(database) or owner["native"] != list(native):
                raise ValueError("Local original has another native owner")
            manifest = json.loads(row["manifest_json"])
            for descriptor in manifest["originals"]:
                if descriptor["sha256"] == sha:
                    root = catalog._root(database, native)
                    result.append(
                        dict(
                            kind="catalog",
                            record=row,
                            path=str(catalog._path(root / "objects" / sha)),
                            descriptor=descriptor,
                            store=str(root),
                        )
                    )
    # Keep every exact proof; do not pick a latest owner or merge paper identities.
    return sorted({canonical_json(row): row for row in result}.values(), key=canonical_json)


def _observe(data, current):
    reads._check(current)
    database = Path(data["database"])
    if reads._native(database) != tuple(data["native"]):
        raise ValueError("Original material database was replaced")
    files, natives = {}, {str(database): tuple(data["native"])}
    with closing(reads._connect(database)) as conn:
        actual = next(row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main")
        if catalog._path(actual) != database:
            raise ValueError("Material read opened another database")
        paper = catalog._paper(conn, data["paper_id"])
        epoch = parent_lifecycle(conn, "paper", data["paper_id"])
        if paper is None or epoch is None:
            raise ValueError("Material parent lifetime is unavailable")
        indexes = []
        if data["mode"] == "managed":
            client = runtime(database=database)
            if client is None:
                raise ValueError("Managed material binding is unavailable")
            rows = conn.execute(
                "SELECT workspace,blob_root,projection_root,legacy_root,generation "
                "FROM document_reader_paths LIMIT 2"
            ).fetchall()
            if len(rows) != 1 or tuple(rows[0]) != tuple(data["registration"]):
                raise ValueError("Original reader registration changed")
            store = _ReadOnlyStore(Path(rows[0][1]))
            owner, scope = _runtime(client, store, data["native"])
            target = _target(conn, owner, scope, data["paper_id"], data["portable_id"])
            if (
                target["binding"] != data["binding"]
                or target["parent_incarnation"] != data["parent_incarnation"]
            ):
                raise ValueError("Material original parent/binding changed")
            operation = None
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='research_file_desired'"
            ).fetchone():
                operation = desired_file(
                    conn, file_id(data["portable_id"], "original_source", data["document_hash"])
                )
            sources = []
            if operation is not None:
                if not paper_current(conn, operation):
                    raise ValueError("Material original source parent retired")
                paths = conn.execute(
                    "SELECT workspace,blob_root,version_root FROM research_file_paths LIMIT 2"
                ).fetchall()
                if (
                    len(paths) != 1
                    or paths[0][0] != owner.workspace
                    or catalog._path(paths[0][1]) != scope.root
                ):
                    raise ValueError("Material original store registration differs")
                payload = operation["payload"]
                if (
                    payload["feature"] != "original_source"
                    or payload["slot"] != data["document_hash"]
                ):
                    raise ValueError("Material original source identity differs")
                sources = [
                    dict(
                        kind="managed",
                        operation=operation,
                        path=str(scope.root / "objects" / data["document_hash"]),
                        descriptor=payload["assets"][0],
                        store=str(scope.root),
                        paths=list(paths[0]),
                    )
                ]
            authority = dict(target=target, sources=sources, registration=list(rows[0]))
            for path in (scope.root, scope.root / "objects", scope.root / "partial", scope.index):
                natives[str(path)] = reads._native(path)
            indexes.append(str(scope.index))
        else:
            catalog._database(conn, database, data["native"])
            sources = _local_sources(
                conn,
                database,
                data["native"],
                data["paper_id"],
                epoch,
                data["document_hash"],
                files,
                current,
            )
            authority = dict(paper=paper, parent_token=epoch, sources=sources)
        for source in sources:
            path = catalog._path(source["path"])
            files[str(path)] = reads._version(path)
            if files[str(path)][2] != source["descriptor"]["size"]:
                raise ValueError("Retained material original size changed")
            folders = [path.parent]
            if source.get("receipt"):
                folders.append(Path(source["receipt"]).parent)
            for folder in folders:
                natives[str(folder)] = reads._native(folder)
            if source.get("store"):
                root = Path(source["store"])
                for path in (root, root / "objects", root / "partial", root / "index.sqlite"):
                    natives[str(path)] = reads._native(path)
                indexes.append(str(root / "index.sqlite"))
            if source["kind"] == "managed":
                for row in (
                    source["operation"]["payload"]["body"],
                    *source["operation"]["payload"]["assets"],
                ):
                    original = catalog._path(Path(source["store"]) / "objects" / row["sha256"])
                    files[str(original)] = reads._version(original)
        reads._check(current)
    if reads._native(database) != tuple(data["native"]):
        raise ValueError("Original material database changed during observation")
    return authority, files, natives, tuple(sorted(set(indexes)))


def _owned_bytes(authority, files, current):
    result, chosen = None, None
    for source in authority["sources"]:
        if source.get("store"):
            store = _ReadOnlyStore(Path(source["store"]))
            if source["kind"] == "managed":
                values = {}

                def read(row, selected_store=store, selected_values=values):
                    value = reads._blob(selected_store, row, files, current)
                    selected_values[row["sha256"]] = value
                    return value

                validate_closure(source["operation"]["payload"], read)
                value = values[source["descriptor"]["sha256"]]
            else:
                value = reads._blob(store, source["descriptor"], files, current)
        else:
            value = reads._read(Path(source["path"]), source["descriptor"]["size"], files, current)
            if hashlib.sha256(value).hexdigest() != source["descriptor"]["sha256"]:
                raise ValueError("Retained material receipt bytes changed")
        if result is not None and value != result:
            raise ValueError("Ambiguous retained material originals disagree")
        result, chosen = value, Path(source["path"])
    return result, chosen


def capture_collection(
    database, paper_id, document, materials, *, expected_native, current=lambda: True
):
    """Worker: actual intact reader source + exact content + independent original owner.

    A retained reader A may be intact while B is desired. Missing historical
    ownership preserves the scientific projection with historical_available=False.
    """
    reads._check(current)
    database, native = catalog._path(database), catalog._expected(expected_native)
    if reads._native(database) != native:
        raise ValueError("Capture requires the original native material database")
    if (
        not isinstance(document, ResolvedDocument)
        or not isinstance(document._owner, DocumentReader)
        or document.local_id != paper_id
        or document._owner.db_path.resolve() != database
        or not document._owner.intact(document)
    ):
        raise ValueError("Use the actual intact reader document used to collect materials")
    if materials.paper_id != paper_id:
        raise ValueError("Material collection belongs to another paper")
    items = project_items(materials)
    used_files = {}
    if not 0 < document.path.stat().st_size <= MAX_PDF_BYTES:
        raise ValueError("Used material source exceeds its PDF bound")
    used = reads._read(document.path, document.path.stat().st_size, used_files, current)
    if (
        hashlib.sha256(used).hexdigest() != document.sha256
        or reads._version(document.path) != document._identity
    ):
        raise ValueError("Collected material source bytes/version differ from the actual reader")
    data = dict(
        database=str(database),
        native=list(native),
        paper_id=paper_id,
        document_hash=document.sha256,
        mode="managed" if document.managed else "local",
    )
    if document.managed:
        data.update(
            portable_id=document.paper_id,
            binding=list(document._context[0]),
            registration=list(document._context[1]),
            parent_incarnation=document.target["parent_incarnation"],
        )
    authority, files, natives, indexes = _observe(data, current)
    original, _path = _owned_bytes(authority, files, current)
    if original is not None and original != used:
        raise ValueError("Retained original differs from the material's actual used source")
    with pymupdf.open(stream=used, filetype="pdf") as pdf:
        if pdf.needs_pass or pdf.page_count < 1:
            raise ValueError("Used material PDF is unavailable")
        pages = pdf.page_count
    if not document._owner.intact(document) or reads._version(document.path) != document._identity:
        raise ValueError("Used collection source changed before capture completed")
    reads._check(current)
    captured = _make(
        Collection,
        database=database,
        paper_id=paper_id,
        document_hash=document.sha256,
        mode=data["mode"],
        pages=pages,
        items=items,
        historical_available=original is not None,
        unavailable_reason=None if original is not None else "original_not_retained",
        _json=canonical_json(data).decode(),
        _authority=canonical_json(authority).decode(),
        _files=tuple(files.items()),
        _natives=tuple(natives.items()),
        _indexes=indexes,
        _used_source=_freeze(
            dict(
                path=str(document.path),
                version=used_files[str(document.path)],
                document_hash=document.sha256,
            )
        ),
        _fence=reads._fence((database, *indexes)),
    )
    _verify(captured, current)
    return captured


def _verify(collection, current):
    _sealed(collection, Collection)
    reads._check(current)
    for path, native in collection._natives:
        if reads._native(path) != native:
            raise ValueError("Original material database/store native identity changed")
    catalog._files_current(collection._files)
    authority, files, natives, indexes = _observe(json.loads(collection._json), current)
    if canonical_json(authority).decode() != collection._authority:
        raise ValueError("Original material source owner/parent/body changed")
    if (
        tuple(files.items()) != collection._files
        or tuple(natives.items()) != collection._natives
        or indexes != collection._indexes
    ):
        raise ValueError("Original material source/receipt version changed")
    return authority


def select(collection, key, payload, *, current=lambda: True):
    """GUI-small metadata/native-only selection, not a bare dictionary read grant."""
    _sealed(collection, Collection)
    reads._check(current)
    item = next((item for item in collection.items if item.key == key), None)
    if item is None or _freeze(payload) != item._payload:
        raise ValueError("Select the exact item in this captured material collection")
    if _native_status(collection, current) == "revoked":
        raise ValueError("Material collection native context was retired")
    return _make(Selection, collection=collection, item=item)


def _native_status(collection, current):
    if not current():
        return "revoked"
    try:
        for path, native in collection._natives:
            if reads._native(path) != native:
                return "revoked"
        catalog._files_current(collection._files)
        fence = reads._fence((collection.database, *collection._indexes))
        state = "ready" if fence == collection._fence else "recheck"
        return state if current() else "revoked"
    except (OSError, ValueError):
        return "revoked"


def _locator(payload, document, sha):
    page = payload.get("page")
    valid_page = type(page) is int and 1 <= page <= document.page_count
    source = dict(kind=payload["kind"], document_hash=sha, page=page if valid_page else None)
    status = "page_only" if valid_page else "unlocated"
    text = payload.get("text") or payload.get("caption")
    if isinstance(text, str) and len(text.encode()) <= 8192:
        source["text"] = text  # Exact declared text, never a semantic/located-quote claim.
    rect = payload.get("rect")
    if (
        valid_page
        and isinstance(rect, list)
        and len(rect) == 4
        and all(type(n) in (int, float) and math.isfinite(n) for n in rect)
    ):
        bounds = document.load_page(page - 1).rect
        if 0 <= rect[0] < rect[2] <= bounds.width and 0 <= rect[1] < rect[3] <= bounds.height:
            source["rect"] = rect
            status = "declared_geometry"
    return _freeze(source), status


def prepare(selection, *, current=lambda: True):
    """Worker: retain no new authority; verify owned A and deliver immutable PDF bytes."""
    _sealed(selection, Selection)
    collection = selection.collection
    authority = _verify(collection, current)
    if not collection.historical_available:
        raise OriginalUnavailable("Material original is not retained by this paper")
    source = selection.payload
    if source.get("document_hash") != collection.document_hash:
        raise OriginalUnavailable("This material has unknown or different source identity")
    before = reads._fence((collection.database, *collection._indexes))
    files = dict(collection._files)
    pdf, path = _owned_bytes(authority, files, current)
    if pdf is None:
        raise OriginalUnavailable("Material original ownership is unavailable")
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        if document.needs_pass or document.page_count != collection.pages:
            raise ValueError("Material original PDF changed")
        document.load_page(0)
        locator, locator_status = _locator(source, document, collection.document_hash)
    _verify(collection, current)
    if before != reads._fence((collection.database, *collection._indexes)):
        raise ValueError("Material metadata interfered; recheck in worker")
    reads._check(current)
    return _make(
        OriginalProof,
        database=collection.database,
        selection=selection,
        document_hash=collection.document_hash,
        data=pdf,
        pages=collection.pages,
        source_path=path,
        _source=locator,
        locator_status=locator_status,
        _fence=before,
    )


def revalidate(proof, *, current=lambda: True):
    """Worker semantic revalidation of the same selection; never recapture current B."""
    _sealed(proof, OriginalProof)
    return prepare(proof.selection, current=current)


def gui_status(proof, *, current=lambda: True):
    """No SQL, hashing, JSON or PDF parsing; recheck is never fresh source authority."""
    _sealed(proof, OriginalProof)
    collection = proof.selection.collection
    state = _native_status(collection, current)
    if state == "revoked":
        return state
    state = (
        "ready"
        if reads._fence((collection.database, *collection._indexes)) == proof._fence
        else "recheck"
    )
    return state if current() else "revoked"
