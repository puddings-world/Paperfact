"""App-scoped personal Drive objects and conditional metadata heads.

No app settings, native vault, research database or implicit authorization. Callers
capture the Google session and explicitly choose their private workspace first.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

import httpx

FILES = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
METADATA = "https://www.googleapis.com/drive/v2/files"
ABOUT = "https://www.googleapis.com/drive/v3/about"
FORMAT = "paperfact.drive-head.v1"
MAX_JSON = 1024 * 1024
MAX_HEAD = 8192
MAX_INLINE = 4 * 1024**2
_ID = re.compile(r"[A-Za-z0-9_-]{1,256}")
_HASH = re.compile(r"[0-9a-f]{64}")
_FIELDS = "id,name,mimeType,parents,ownedByMe,shared,appProperties,size,sha256Checksum,version"


class DriveChanged(ConnectionError):
    """Another writer committed first; preserve intent and reload before retry."""


class DriveUnavailable(ConnectionError):
    """A transient provider failure, never an empty remote workspace."""


class DriveMissing(FileNotFoundError):
    """Expected cloud data is missing; never silently initialize over it."""


def identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Invalid Drive file identity")
    return value


def origin(folder):
    label = hashlib.sha256(identifier(folder).encode()).hexdigest()[:40]
    return "https://" + label + ".paperfact-drive.invalid"


def encode(value, maximum=MAX_JSON):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > maximum:
        raise ValueError("Drive record exceeds its limit")
    return raw


def decode(raw, maximum=MAX_JSON):
    if not isinstance(raw, bytes) or len(raw) > maximum:
        raise ValueError("Drive record exceeds its limit")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate Drive record field")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("Nonfinite Drive record")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("Unreadable Drive record") from exc


def head_body(value):
    from paper_daily.sync_journal import _identifier

    if not isinstance(value, dict) or set(value) != {
        "format", "workspace_id", "generation", "commit"
    } or value["format"] != FORMAT:
        raise ValueError("Unsupported personal Drive workspace head")
    _identifier(value["workspace_id"])
    if type(value["generation"]) is not int or not 0 <= value["generation"] < 2**53:
        raise ValueError("Invalid Drive generation")
    ref = value["commit"]
    if ref is not None:
        if not isinstance(ref, dict) or set(ref) != {"id", "sha256", "size"}:
            raise ValueError("Invalid Drive commit reference")
        identifier(ref["id"])
        if (not isinstance(ref["sha256"], str) or not _HASH.fullmatch(ref["sha256"])
                or type(ref["size"]) is not int or not 0 < ref["size"] <= 64 * 1024**2):
            raise ValueError("Invalid Drive commit size or hash")
    if (value["generation"] == 0) != (ref is None):
        raise ValueError("Drive generation and commit disagree")
    return encode(value, MAX_HEAD)


@dataclass(frozen=True)
class Head:
    file_id: str
    workspace_id: str
    etag: str
    body: bytes

    def value(self):
        return decode(self.body, MAX_HEAD)


class DriveFiles:
    """One captured official Google session; no cookies, redirects or token logging."""

    def __init__(self, session, *, client=None, cancelled=lambda: False):
        self.session, self.cancelled = session, cancelled
        self.client = client or httpx.Client(timeout=20, trust_env=False, follow_redirects=False)
        self._owned = client is None
        self._heads = {}

    def close(self):
        if self._owned:
            self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def check(self):
        if self.cancelled():
            from paper_daily.workspace_service import Cancelled

            raise Cancelled("Personal Drive work stopped")

    def request(self, method, url, *, headers=None, **kwargs):
        self.check()
        if not any(url == base or url.startswith(base + "/")
                   for base in (FILES, UPLOAD, METADATA, ABOUT)):
            raise ValueError("Drive credentials require an official API destination")
        if any(key.lower() == "authorization" for key in (headers or {})):
            raise ValueError("Drive authorization is owned by the captured session")
        auth = {"Authorization": "Bearer " + self.session.access_token()}
        try:
            with self.client.stream(method, url, headers=auth | (headers or {}), **kwargs) as reply:
                parts, size = [], 0
                for chunk in reply.iter_bytes():
                    self.check()
                    size += len(chunk)
                    if size > MAX_INLINE:
                        raise ValueError("Drive response exceeds its bounded transfer limit")
                    parts.append(chunk)
                # iter_bytes already decoded the wire representation. Keeping gzip
                # or its encoded length would make the reconstructed response decode twice.
                headers = {key: value for key, value in reply.headers.items()
                           if key.lower() not in {
                               "content-encoding", "content-length", "transfer-encoding"}}
                response = httpx.Response(reply.status_code, headers=headers,
                                          content=b"".join(parts), request=reply.request)
        except httpx.TransportError as exc:
            raise DriveUnavailable("Drive is unavailable; local changes are retained") from exc
        self.check()
        if response.status_code == 412:
            raise DriveChanged("Drive changed before publication")
        if response.status_code == 404:
            raise DriveMissing("Expected Drive file is missing")
        if response.status_code in (401, 403):
            raise PermissionError("Drive authorization or access needs attention")
        if response.status_code == 429 or response.status_code >= 500:
            raise DriveUnavailable("Drive request must be retried later")
        if response.status_code not in (200, 201, 204, 206, 308, 409):
            raise ValueError("Unexpected Drive response status")
        return response

    @staticmethod
    def json(response):
        value = decode(response.content)
        if not isinstance(value, dict):
            raise ValueError("Invalid Drive response")
        return value

    def account(self):
        response = self.request("GET", ABOUT, params={"fields": "user(permissionId,emailAddress)"})
        user = self.json(response).get("user")
        if not isinstance(user, dict):
            raise ValueError("Drive did not identify the account")
        identity = identifier(user.get("permissionId"))
        email = user.get("emailAddress")
        if (not isinstance(email, str) or len(email) > 320
                or any(ord(c) < 32 or ord(c) == 127 for c in email)):
            raise ValueError("Drive did not identify the account label")
        return {"id": identity, "email": email}

    def new_ids(self, count=1):
        if type(count) is not int or not 1 <= count <= 100:
            raise ValueError("Request between one and 100 Drive identities")
        value = self.json(self.request("GET", FILES + "/generateIds",
                                      params={"count": count, "space": "drive", "type": "files"}))
        ids = value.get("ids")
        if not isinstance(ids, list) or len(ids) != count:
            raise ValueError("Drive did not allocate distinct identities")
        ids = [identifier(item) for item in ids]
        if len(set(ids)) != count:
            raise ValueError("Drive did not allocate distinct identities")
        return [identifier(item) for item in ids]

    def metadata(self, file_id):
        value = self.json(self.request("GET", FILES + "/" + identifier(file_id),
                                      params={"fields": _FIELDS}))
        if value.get("id") != file_id or value.get("ownedByMe") is not True:
            raise PermissionError("This is not the selected account's Drive file")
        if value.get("shared") is not False:
            raise PermissionError("Personal sync requires private Drive files")
        return value

    def owned(self, file_id, workspace_id, role, *, parent=None):
        value = self.metadata(file_id)
        if value.get("appProperties") != {
            "pfWorkspace": workspace_id, "pfRole": role, "pfVersion": "1"
        }:
            raise ValueError("Drive file does not belong to this workspace format")
        if parent is not None and value.get("parents") != [identifier(parent)]:
            raise ValueError("Drive workspace location changed")
        return value

    def create_folder(self, file_id, workspace_id, name, *, directory=False):
        from paper_daily.sync_journal import _identifier

        _identifier(workspace_id)
        identifier(file_id)
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError("Choose a short workspace name")
        role = "directory" if directory else "workspace"
        metadata = {"id": file_id, "name": name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "appProperties": {"pfWorkspace": workspace_id,
                                      "pfRole": role, "pfVersion": "1"}}
        response = self.request("POST", FILES, params={"fields": "id"}, json=metadata)
        if response.status_code == 409:
            return self.owned(file_id, workspace_id, role)
        if self.json(response).get("id") != file_id:
            raise ValueError("Drive created another workspace identity")
        return self.owned(file_id, workspace_id, role)

    def put_small(self, file_id, parent, workspace_id, role, data, *, description=None,
                  folder_role="workspace"):
        from paper_daily.sync_journal import _identifier

        _identifier(workspace_id)
        identifier(file_id)
        identifier(parent)
        if role not in {"head", "commit", "blob"}:
            raise ValueError("Unknown private Drive file role")
        if not isinstance(data, bytes) or len(data) > MAX_INLINE:
            raise ValueError("Use bounded small immutable Drive objects")
        if description is not None and (
            role != "head" or not isinstance(description, str)
            or len(description.encode("utf-8")) > MAX_HEAD
        ):
            raise ValueError("Only a bounded head may carry metadata")
        metadata = {"id": file_id, "name": role + "-" + file_id,
                    "mimeType": "application/octet-stream", "parents": [parent],
                    "appProperties": {"pfWorkspace": workspace_id,
                                      "pfRole": role, "pfVersion": "1"}}
        if description is not None:
            validated = head_body(decode(description.encode("utf-8"), MAX_HEAD))
            if decode(validated)["workspace_id"] != workspace_id:
                raise ValueError("Drive head belongs to another workspace")
            metadata["description"] = validated.decode("utf-8")
        elif role == "head":
            raise ValueError("A new Drive head requires its initial metadata")
        self.owned(parent, workspace_id, folder_role)
        boundary = "paperfact-" + hashlib.sha256(file_id.encode()).hexdigest()
        body = (b"--" + boundary.encode() + b"\r\nContent-Type: application/json\r\n\r\n"
                + encode(metadata) + b"\r\n--" + boundary.encode()
                + b"\r\nContent-Type: application/octet-stream\r\n\r\n" + data
                + b"\r\n--" + boundary.encode() + b"--\r\n")
        response = self.request("POST", UPLOAD, params={"uploadType": "multipart", "fields": "id"},
                                content=body, headers={"Content-Type":
                                "multipart/related; boundary=" + boundary})
        if response.status_code != 409 and self.json(response).get("id") != file_id:
            raise ValueError("Drive created another object identity")
        value = self.owned(file_id, workspace_id, role, parent=parent)
        if role != "head":
            expected = hashlib.sha256(data).hexdigest()
            if value.get("sha256Checksum") != expected or value.get("size") != str(len(data)):
                raise ValueError("Drive object bytes differ from the captured upload")
        return value

    def read_head(self, file_id, parent, workspace_id, *, folder_role="workspace"):
        self.owned(parent, workspace_id, folder_role)
        self.owned(file_id, workspace_id, "head", parent=parent)
        value = self.json(self.request("GET", METADATA + "/" + identifier(file_id),
                                      params={"fields": "id,etag,description"}))
        etag, description = value.get("etag"), value.get("description")
        if (value.get("id") != file_id or not isinstance(etag, str)
                or not re.fullmatch(r'"[!#-~]{1,255}"', etag)
                or not isinstance(description, str)):
            raise ValueError("Drive did not provide a strong conditional metadata head")
        body = head_body(decode(description.encode("utf-8"), MAX_HEAD))
        if decode(body)["workspace_id"] != workspace_id:
            raise ValueError("Drive head belongs to another workspace")
        observed = Head(file_id, workspace_id, etag, body)
        self._heads[file_id] = (observed, parent)
        return observed

    def check_head(self, observed):
        if (not isinstance(observed, Head) or observed.file_id not in self._heads
                or self._heads[observed.file_id][0] is not observed):
            raise ValueError("Read this account's current Drive head before publishing")
        return self._heads[observed.file_id][1]

    def publish_head(self, observed, new_commit, *, folder_role="workspace"):
        parent = self.check_head(observed)
        self.owned(parent, observed.workspace_id, folder_role)
        self.owned(observed.file_id, observed.workspace_id, "head", parent=parent)
        value = observed.value()
        replacement = head_body({**value, "generation": value["generation"] + 1,
                                 "commit": new_commit})
        response = self.request("PATCH", METADATA + "/" + identifier(observed.file_id),
                                params={"fields": "id,etag,description"},
                                json={"description": replacement.decode("utf-8")},
                                headers={"If-Match": observed.etag})
        accepted = self.json(response)
        if (accepted.get("id") != observed.file_id or accepted.get("description") !=
                replacement.decode("utf-8") or not isinstance(accepted.get("etag"), str)
                or not re.fullmatch(r'"[!#-~]{1,255}"', accepted["etag"])
                or accepted["etag"] == observed.etag):
            raise ValueError("Drive did not confirm the exact conditional publication")
        current = Head(observed.file_id, observed.workspace_id, accepted["etag"], replacement)
        self._heads[observed.file_id] = (current, parent)
        return current

    def read_small(self, reference, parent, workspace_id, role="commit"):
        """Fetch immutable bytes only after checking their captured workspace and digest."""
        if not isinstance(reference, dict) or set(reference) != {"id", "sha256", "size"}:
            raise ValueError("Invalid immutable Drive reference")
        file_id = identifier(reference["id"])
        digest, size = reference["sha256"], reference["size"]
        if (not isinstance(digest, str) or not _HASH.fullmatch(digest)
                or type(size) is not int or not 0 < size <= MAX_INLINE):
            raise ValueError("Invalid immutable Drive byte limit")
        value = self.owned(file_id, workspace_id, role, parent=parent)
        if value.get("sha256Checksum") != digest or value.get("size") != str(size):
            raise ValueError("Drive object metadata differs from its captured reference")
        raw = self.request("GET", FILES + "/" + file_id, params={"alt": "media"}).content
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Drive object bytes failed verification")
        return raw


    def workspaces(self, *, directories=False):
        """List only private, app-created workspace folders and their single head."""
        role = "directory" if directories else "workspace"
        query = ("trashed=false and mimeType='application/vnd.google-apps.folder' and "
                 f"appProperties has {{ key='pfRole' and value='{role}' }}")
        value = self.json(self.request("GET", FILES, params={
            "q": query, "fields": "nextPageToken,files(" + _FIELDS + ")", "pageSize": 100}))
        if value.get("nextPageToken"):
            raise ValueError("More than 100 Drive workspaces; narrow the account first")
        rows = value.get("files")
        if not isinstance(rows, list):
            raise ValueError("Drive did not return a workspace list")
        result = []
        for row in rows:
            props = row.get("appProperties", {}) if isinstance(row, dict) else {}
            workspace = props.get("pfWorkspace")
            if not workspace or row.get("shared") is not False or row.get("ownedByMe") is not True:
                continue
            folder = identifier(row.get("id"))
            self.owned(folder, workspace, role)
            heads = self.json(self.request("GET", FILES, params={
                "q": f"trashed=false and '{folder}' in parents and "
                     "appProperties has { key='pfRole' and value='head' }",
                "fields": "nextPageToken,files(id)", "pageSize": 2}))
            items = heads.get("files")
            if not isinstance(items, list) or len(items) != 1 or heads.get("nextPageToken"):
                continue  # Incomplete setup stays private; never guess a head.
            head_id = identifier(items[0].get("id"))
            self.read_head(head_id, folder, workspace, folder_role=role)
            result.append(dict(folder_id=folder, head_id=head_id, workspace_id=workspace,
                               name=str(row.get("name", "Paperfact"))[:200]))
        return sorted(result, key=lambda row: row["name"].casefold())
