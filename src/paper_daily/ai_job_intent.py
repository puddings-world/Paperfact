"""Private immutable routing values; no configuration, provider or filesystem reads.

These values are not credentials storage, workspace authority or an active facade.
Only an already-resolved Settings object can supply a route.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from itertools import islice

from paper_daily.ai_types import Settings

MAX_PAYLOAD_BYTES = 1024 * 1024
MAX_TEXT_BYTES = 64 * 1024
MAX_ROUTES = 64
MAX_PROFILES = 64
MAX_ARGUMENTS = 128
MAX_ARGUMENT_BYTES = 16 * 1024
MAX_COMMAND_BYTES = 64 * 1024
VERSION = 1

_SETTINGS_FIELDS = (
    "backend",
    "model",
    "api_key",
    "base_url",
    "profile",
    "api_key_env",
    "max_tokens",
    "token_parameter",
    "requires_key",
    "isolated",
    "account_id",
    "cli_home",
)
_TEXT_FIELDS = {"model", "api_key", "base_url", "profile", "api_key_env", "account_id", "cli_home"}
_TASK = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_PROFILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_BACKEND = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_REQUEST = re.compile(r"(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\Z")


class JobIntentError(ValueError):
    """A fixed public code, never caller-provided values or exception details."""

    def __init__(self, code):
        allowed = {
            "invalid_text",
            "budget_exceeded",
            "invalid_request_id",
            "invalid_command",
            "invalid_object",
            "unknown_or_missing_fields",
            "invalid_settings",
            "unresolved_route",
            "invalid_routes",
            "invalid_payload",
            "undeclared_task",
            "undeclared_profile",
            "unsupported_version",
            "invalid_expected_binding",
            "invalid_intent",
            "frame_read_failed",
            "invalid_binary_stream",
            "truncated_frame",
            "duplicate_field",
            "invalid_json_constant",
            "invalid_frame_magic",
            "invalid_job_payload",
            "request_mismatch",
            "command_mismatch",
            "invalid_frame_bytes",
            "unexpected_frame_bytes",
            "frame_write_failed",
            "invalid_expected_phase",
            "invalid_control_line",
            "incomplete_control_line",
            "unexpected_control_phase",
        }
        safe = code if type(code) is str and code in allowed else "invalid_intent"
        self.code = safe
        super().__init__(safe)


def _text(value, *, nullable=False, limit=MAX_TEXT_BYTES):
    if value is None and nullable:
        return value
    if type(value) is not str or "\0" in value:
        raise JobIntentError("invalid_text")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        raise JobIntentError("invalid_text") from None
    if size > limit:
        raise JobIntentError("budget_exceeded")
    return value


def _name(value, pattern, code):
    if type(value) is not str or not pattern.fullmatch(value):
        raise JobIntentError(code)
    return value


def _request_id(value):
    return _name(value, _REQUEST, "invalid_request_id")


def _command(value):
    if type(value) not in (list, tuple) or not 1 <= len(value) <= MAX_ARGUMENTS:
        raise JobIntentError("invalid_command")
    result = tuple(_text(arg, limit=MAX_ARGUMENT_BYTES) for arg in value)
    _name(result[0], _BACKEND, "invalid_command")
    if sum(len(arg.encode("utf-8")) + 1 for arg in result) > MAX_COMMAND_BYTES:
        raise JobIntentError("budget_exceeded")
    return result


def _closed(value, names):
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise JobIntentError("invalid_object")
    if set(value) != set(names):
        raise JobIntentError("unknown_or_missing_fields")


def _settings(value):
    if type(value) is not Settings or tuple(f.name for f in fields(Settings)) != _SETTINGS_FIELDS:
        raise JobIntentError("invalid_settings")
    record = {name: getattr(value, name) for name in _SETTINGS_FIELDS}
    _name(record["backend"], _BACKEND, "invalid_settings")
    if record["backend"] == "auto":
        raise JobIntentError("unresolved_route")
    for name in _TEXT_FIELDS:
        _text(record[name], nullable=True)
    if type(record["max_tokens"]) is not int or record["max_tokens"] < 1:
        raise JobIntentError("invalid_settings")
    if type(record["token_parameter"]) is not str or record["token_parameter"] not in (
        "max_tokens",
        "max_completion_tokens",
    ):
        raise JobIntentError("invalid_settings")
    if any(type(record[name]) is not bool for name in ("requires_key", "isolated")):
        raise JobIntentError("invalid_settings")
    account = record["account_id"]
    if account and not re.fullmatch(r"[0-9a-f]{32}", account):
        raise JobIntentError("invalid_settings")
    key = record["api_key_env"]
    if key and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise JobIntentError("invalid_settings")
    return tuple(record[name] for name in _SETTINGS_FIELDS)


def _settings_data(value):
    _closed(value, _SETTINGS_FIELDS)
    return Settings(**value)


def _copy_settings(values):
    return Settings(**dict(zip(_SETTINGS_FIELDS, values, strict=True)))


def _routes(value, *, profiles=False):
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise JobIntentError("invalid_routes")
    maximum = MAX_PROFILES if profiles else MAX_ROUTES
    try:
        entries = list(islice(value.items(), maximum + 1))
    except Exception:
        raise JobIntentError("invalid_routes") from None
    if len(entries) > maximum:
        raise JobIntentError("budget_exceeded")
    result, seen = [], set()
    total = 0
    for entry in entries:
        if type(entry) not in (list, tuple) or len(entry) != 2:
            raise JobIntentError("invalid_routes")
        key, cfg = entry
        _name(key, _PROFILE if profiles else _TASK, "invalid_routes")
        if key in seen or (not profiles and key == "default"):
            raise JobIntentError("invalid_routes")
        seen.add(key)
        route = _settings(cfg)
        total += sum(len(item.encode("utf-8")) for item in route if type(item) is str)
        if total > MAX_PAYLOAD_BYTES:
            raise JobIntentError("budget_exceeded")
        result.append((key, route))
    return tuple(sorted(result))


def _json_bytes(value):
    """Incremental bounded encoding: never allocate an oversized joined payload."""
    chunks, total = [], 0
    try:
        encoder = json.JSONEncoder(
            ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
        for piece in encoder.iterencode(value):
            encoded = piece.encode("utf-8")
            total += len(encoded)
            if total > MAX_PAYLOAD_BYTES:
                raise JobIntentError("budget_exceeded")
            chunks.append(encoded)
    except JobIntentError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise JobIntentError("invalid_payload") from None
    return b"".join(chunks)


@dataclass(frozen=True, slots=True, init=False, repr=False)
class FrozenRoutes:
    """Defensive primitive copies of already-resolved routes, not a live resolver."""

    _default: tuple
    _tasks: tuple
    _profiles: tuple
    _account_directory: str | None

    def __init__(
        self,
        default: Settings,
        tasks: Mapping[str, Settings],
        *,
        profiles=None,
        account_directory: str | None = None,
    ):
        object.__setattr__(self, "_default", _settings(default))
        object.__setattr__(self, "_tasks", _routes(tasks))
        object.__setattr__(self, "_profiles", _routes(profiles, profiles=True))
        object.__setattr__(self, "_account_directory", _text(account_directory, nullable=True))
        _json_bytes(self.to_data())

    def __repr__(self):
        return f"FrozenRoutes(tasks={len(self._tasks)}, profiles={len(self._profiles)})"

    @property
    def task_names(self):
        return tuple(key for key, _ in self._tasks)

    @property
    def profile_names(self):
        return tuple(key for key, _ in self._profiles)

    @property
    def account_directory(self):
        return self._account_directory

    def settings(self, task="default", *, profile=None):
        if type(task) is not str or (task != "default" and task not in self.task_names):
            raise JobIntentError("undeclared_task")
        if profile is not None:
            if type(profile) is not str or profile not in self.profile_names:
                raise JobIntentError("undeclared_profile")
            return _copy_settings(dict(self._profiles)[profile])
        return _copy_settings(self._default if task == "default" else dict(self._tasks)[task])

    def to_data(self):
        return {
            "default": dict(zip(_SETTINGS_FIELDS, self._default, strict=True)),
            "tasks": {
                key: dict(zip(_SETTINGS_FIELDS, value, strict=True)) for key, value in self._tasks
            },
            "profiles": {
                key: dict(zip(_SETTINGS_FIELDS, value, strict=True))
                for key, value in self._profiles
            },
            "account_directory": self._account_directory,
        }

    @classmethod
    def from_data(cls, data):
        _closed(data, ("default", "tasks", "profiles", "account_directory"))
        tasks, profiles = data["tasks"], data["profiles"]
        if type(tasks) is not dict or type(profiles) is not dict:
            raise JobIntentError("invalid_routes")
        if len(tasks) > MAX_ROUTES or len(profiles) > MAX_PROFILES:
            raise JobIntentError("budget_exceeded")
        return cls(
            _settings_data(data["default"]),
            {key: _settings_data(value) for key, value in tasks.items()},
            profiles={key: _settings_data(value) for key, value in profiles.items()},
            account_directory=data["account_directory"],
        )

    def bind(self, request_id, command):
        return BoundJobIntent(self, request_id, command)


@dataclass(frozen=True, slots=True, init=False, repr=False)
class BoundJobIntent:
    """One explicit launch binding; never mints IDs, executes argv or grants writes."""

    _routes: FrozenRoutes
    _request_id: str
    _command: tuple[str, ...]

    def __init__(self, routes, request_id, command):
        if type(routes) is not FrozenRoutes:
            raise JobIntentError("invalid_routes")
        object.__setattr__(self, "_routes", FrozenRoutes.from_data(routes.to_data()))
        object.__setattr__(self, "_request_id", _request_id(request_id))
        object.__setattr__(self, "_command", _command(command))
        _json_bytes(self.to_data())

    def __repr__(self):
        return "BoundJobIntent(version=1, command=<redacted>, routes=<private>)"

    @property
    def routes(self):
        return FrozenRoutes.from_data(self._routes.to_data())

    @property
    def request_id(self):
        return self._request_id

    @property
    def command(self):
        return tuple(self._command)

    def to_data(self):
        return {
            "version": VERSION,
            "request_id": self._request_id,
            "command": list(self._command),
            "routes": self._routes.to_data(),
        }

    @classmethod
    def from_data(cls, data):
        _closed(data, ("version", "request_id", "command", "routes"))
        if type(data["version"]) is not int or data["version"] != VERSION:
            raise JobIntentError("unsupported_version")
        return cls(FrozenRoutes.from_data(data["routes"]), data["request_id"], data["command"])
