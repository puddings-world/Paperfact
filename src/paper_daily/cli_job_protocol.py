"""Bounded private binary handoff primitives for the bootstrap and desktop.

No default stdin, environment, executable, provider or file is accessed here.
The caller owns pipe lifetime, startup deadlines, cleanup and process identity.
"""

from __future__ import annotations

import io
import json
import struct

from paper_daily.ai_job_intent import (
    MAX_PAYLOAD_BYTES,
    VERSION,
    BoundJobIntent,
    JobIntentError,
    _command,
    _json_bytes,
    _request_id,
)

MAGIC = b"PFJOB\x00"
_HEADER = struct.Struct(">6sBI")
HEADER_BYTES = _HEADER.size
MAX_CONTROL_BYTES = 128
_CONTROL_PREFIX = b"@paperfact-ai-job"


class JobProtocolError(JobIntentError):
    """Fixed protocol codes never echo payloads, paths, argv or stream errors."""


def _expected(request_id, command):
    try:
        return _request_id(request_id), _command(command)
    except JobIntentError:
        raise JobProtocolError("invalid_expected_binding") from None


def encode_frame(intent):
    if type(intent) is not BoundJobIntent:
        raise JobProtocolError("invalid_intent")
    try:
        payload = _json_bytes(intent.to_data())
    except JobIntentError as error:
        raise JobProtocolError(error.code) from None
    return _HEADER.pack(MAGIC, VERSION, len(payload)) + payload


def _read_exact(stream, length):
    result = bytearray()
    while len(result) < length:
        remaining = length - len(result)
        try:
            chunk = stream.read(remaining)
        except Exception:
            raise JobProtocolError("frame_read_failed") from None
        if type(chunk) is not bytes or len(chunk) > remaining:
            raise JobProtocolError("invalid_binary_stream")
        if not chunk:
            raise JobProtocolError("truncated_frame")
        result.extend(chunk)
    return bytes(result)


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise JobProtocolError("duplicate_field")
        result[key] = value
    return result


def _constant(_value):
    raise JobProtocolError("invalid_json_constant")


def read_frame(stream, *, expected_request_id, expected_command):
    """Consume only this frame. Never read/close/seek subsequent stdin bytes."""
    request_id, command = _expected(expected_request_id, expected_command)
    magic, version, length = _HEADER.unpack(_read_exact(stream, HEADER_BYTES))
    if magic != MAGIC:
        raise JobProtocolError("invalid_frame_magic")
    if version != VERSION:
        raise JobProtocolError("unsupported_version")
    if not 0 < length <= MAX_PAYLOAD_BYTES:
        raise JobProtocolError("budget_exceeded")
    payload = _read_exact(stream, length)
    try:
        data = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        intent = BoundJobIntent.from_data(data)
    except JobProtocolError:
        raise
    except JobIntentError as error:
        raise JobProtocolError(error.code) from None
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise JobProtocolError("invalid_job_payload") from None
    if intent.request_id != request_id:
        raise JobProtocolError("request_mismatch")
    if intent.command != command:
        raise JobProtocolError("command_mismatch")
    return intent


def decode_frame(frame, *, expected_request_id, expected_command):
    """Decode one exact bytes value; use read_frame to preserve trailing stdin."""
    if type(frame) is not bytes:
        raise JobProtocolError("invalid_frame_bytes")
    if len(frame) > HEADER_BYTES + MAX_PAYLOAD_BYTES:
        raise JobProtocolError("budget_exceeded")
    stream = io.BytesIO(frame)
    intent = read_frame(
        stream, expected_request_id=expected_request_id, expected_command=expected_command
    )
    if stream.read(1):
        raise JobProtocolError("unexpected_frame_bytes")
    return intent


def write_frame(stream, intent):
    """Blocking stream primitive; a GUI transport must call this off its GUI thread.

    Partial writes are completed under a finite byte budget. The caller must own
    blocking-I/O deadlines; this function neither starts threads nor closes pipes.
    """
    frame = encode_frame(intent)
    view = memoryview(frame)
    written = 0
    while written < len(frame):
        try:
            count = stream.write(view[written:])
        except Exception:
            raise JobProtocolError("frame_write_failed") from None
        if type(count) is not int or not 0 < count <= len(frame) - written:
            raise JobProtocolError("invalid_binary_stream")
        written += count
    try:
        stream.flush()
    except Exception:
        raise JobProtocolError("frame_write_failed") from None
    return written


def _control_line(phase, request_id):
    try:
        identity = _request_id(request_id)
    except JobIntentError:
        raise JobProtocolError("invalid_request_id") from None
    return _CONTROL_PREFIX + b" 1 " + phase + b" " + identity.encode("ascii") + b"\n"


def hello_line(request_id):
    return _control_line(b"hello", request_id)


def ready_line(request_id):
    return _control_line(b"ready", request_id)


def parse_control_line(line, *, expected_request_id, expected_phase=None):
    """Validate one complete versioned control line, never arbitrary child output."""
    try:
        identity = _request_id(expected_request_id)
    except JobIntentError:
        raise JobProtocolError("invalid_expected_binding") from None
    if expected_phase is not None and (
        type(expected_phase) is not str or expected_phase not in ("hello", "ready")
    ):
        raise JobProtocolError("invalid_expected_phase")
    if type(line) is not bytes or not 0 < len(line) <= MAX_CONTROL_BYTES:
        raise JobProtocolError("invalid_control_line")
    if not line.endswith(b"\n"):
        raise JobProtocolError("incomplete_control_line")
    body = line[:-2] if line.endswith(b"\r\n") else line[:-1]
    parts = body.split(b" ")
    if len(parts) != 4 or parts[0] != _CONTROL_PREFIX:
        raise JobProtocolError("invalid_control_line")
    if parts[1] != b"1":
        raise JobProtocolError("unsupported_version")
    if parts[2] not in (b"hello", b"ready"):
        raise JobProtocolError("invalid_control_line")
    if parts[3] != identity.encode("ascii"):
        raise JobProtocolError("request_mismatch")
    phase = parts[2].decode("ascii")
    if expected_phase is not None and phase != expected_phase:
        raise JobProtocolError("unexpected_control_phase")
    return phase
