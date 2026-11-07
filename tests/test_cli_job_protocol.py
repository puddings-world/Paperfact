"""Bounded binary protocol with fake pipes, never providers or executables."""

import io
import json
import struct
from dataclasses import fields

import pytest
from test_ai_job_intent import ARGV_VALUE, DIRECTORY, REQUEST, SECRET, configured, routes

from paper_daily.ai_job_intent import MAX_PAYLOAD_BYTES, BoundJobIntent, FrozenRoutes
from paper_daily.ai_types import Settings
from paper_daily.cli_job_protocol import (
    HEADER_BYTES,
    MAGIC,
    MAX_CONTROL_BYTES,
    JobProtocolError,
    decode_frame,
    encode_frame,
    hello_line,
    parse_control_line,
    read_frame,
    ready_line,
    write_frame,
)

COMMAND = ("survey", ARGV_VALUE, "--force")


def intent():
    return routes().bind(REQUEST, COMMAND)


def decode(frame, **changes):
    expected = dict(expected_request_id=REQUEST, expected_command=COMMAND)
    expected.update(changes)
    return decode_frame(frame, **expected)


def framed(payload, *, version=1, magic=MAGIC, length=None):
    return (
        struct.pack(">6sBI", magic, version, len(payload) if length is None else length) + payload
    )


def wire(data):
    return framed(json.dumps(data, separators=(",", ":")).encode())


class PartialReader:
    def __init__(self, data):
        self.stream = io.BytesIO(data)
        self.requests = []

    def read(self, count):
        self.requests.append(count)
        assert count > 0  # Never an unbounded .read().
        return self.stream.read(min(count, 3))


class PartialWriter:
    def __init__(self):
        self.data = bytearray()
        self.flushed = False

    def write(self, value):
        chunk = value[:5]
        self.data.extend(chunk)
        return len(chunk)

    def flush(self):
        self.flushed = True


def test_real_fields_round_trip_and_precise_trailing_stdin_preservation():
    frame = encode_frame(intent())
    trailing = b"later ordinary stdin\n\x00\xff"
    source = PartialReader(frame + trailing)
    copy = read_frame(source, expected_request_id=REQUEST, expected_command=COMMAND)
    assert copy.request_id == REQUEST and copy.command == COMMAND
    assert copy.routes.settings("survey") == configured()
    assert copy.routes.settings("survey").model is None
    assert set(copy.routes.to_data()["tasks"]["survey"]) == {item.name for item in fields(Settings)}
    assert source.stream.read() == trailing
    assert source.requests and max(source.requests) <= MAX_PAYLOAD_BYTES
    assert not source.stream.closed


def test_partial_writes_flush_without_closing_or_modifying_intent():
    target = PartialWriter()
    written = write_frame(target, intent())
    assert written == len(target.data) and target.flushed
    assert bytes(target.data) == encode_frame(intent())
    assert decode(bytes(target.data)).routes.account_directory == DIRECTORY


@pytest.mark.parametrize("version", [0, 2, 255])
def test_unknown_header_versions_refuse_before_consuming_payload(version):
    payload = b"never read this payload"
    source = io.BytesIO(framed(payload, version=version))
    with pytest.raises(JobProtocolError, match="unsupported_version"):
        read_frame(source, expected_request_id=REQUEST, expected_command=COMMAND)
    assert source.tell() == HEADER_BYTES
    assert source.read() == payload


@pytest.mark.parametrize("length", [0, MAX_PAYLOAD_BYTES + 1, 2**32 - 1])
def test_zero_or_oversized_header_never_reads_declared_body(length):
    source = io.BytesIO(framed(b"body", length=length))
    with pytest.raises(JobProtocolError, match="budget_exceeded"):
        read_frame(source, expected_request_id=REQUEST, expected_command=COMMAND)
    assert source.tell() == HEADER_BYTES and source.read() == b"body"


@pytest.mark.parametrize("cut", [0, 1, HEADER_BYTES - 1, HEADER_BYTES, HEADER_BYTES + 20])
def test_truncated_header_or_payload_is_an_error_not_a_live_settings_fallback(cut):
    with pytest.raises(JobProtocolError, match="truncated_frame"):
        decode(encode_frame(intent())[:cut])


@pytest.mark.parametrize("payload", [b"{broken", b"\xff", b"[]", b"null", b'"text"', b'{"n":NaN}'])
def test_malformed_utf8_json_shapes_and_constants_do_not_expose_payload(payload):
    with pytest.raises(JobProtocolError) as error:
        decode(framed(payload))
    assert SECRET not in str(error.value) + repr(error.value)


@pytest.mark.parametrize("location", ["job", "routes", "settings"])
def test_duplicate_keys_at_every_closed_level_are_rejected(location):
    raw = json.dumps(intent().to_data(), separators=(",", ":"))
    if location == "job":
        raw = raw.replace('"version":1', '"version":1,"version":1', 1)
    elif location == "routes":
        raw = raw.replace('"profiles":{', '"account_directory":null,"profiles":{', 1)
    else:
        raw = raw.replace('"backend":"none"', '"backend":"none","backend":"none"', 1)
    with pytest.raises(JobProtocolError, match="duplicate_field"):
        decode(framed(raw.encode()))


@pytest.mark.parametrize("location", ["job", "routes", "settings"])
def test_unknown_fields_and_values_fail_closed_without_secret_in_error(location):
    data = intent().to_data()
    target = data if location == "job" else data["routes"]
    if location == "settings":
        target = data["routes"]["default"]
    target[SECRET] = DIRECTORY
    with pytest.raises(JobProtocolError) as error:
        decode(wire(data))
    for value in (SECRET, DIRECTORY, ARGV_VALUE):
        assert value not in str(error.value) + repr(error.value)


@pytest.mark.parametrize("version", [True, 0, 2, "1"])
def test_payload_version_is_exact_integer_one(version):
    data = intent().to_data()
    data["version"] = version
    with pytest.raises(JobProtocolError, match="unsupported_version"):
        decode(wire(data))


def test_request_and_complete_confirmed_command_must_match_exactly():
    frame = encode_frame(intent())
    with pytest.raises(JobProtocolError, match="request_mismatch"):
        decode(frame, expected_request_id="b" * 32)
    with pytest.raises(JobProtocolError, match="command_mismatch"):
        decode(frame, expected_command=COMMAND[:-1])
    with pytest.raises(JobProtocolError, match="command_mismatch"):
        decode(frame, expected_command=("survey", "different-list", "--force"))
    with pytest.raises(JobProtocolError, match="unexpected_frame_bytes"):
        decode(frame + b"X")


def test_invalid_expected_binding_does_not_consume_any_stdin():
    stream = io.BytesIO(encode_frame(intent()))
    with pytest.raises(JobProtocolError, match="invalid_expected_binding"):
        read_frame(stream, expected_request_id=SECRET, expected_command=COMMAND)
    assert stream.tell() == 0


@pytest.mark.parametrize("phase", ["hello", "ready"])
def test_control_lines_are_versioned_bound_nonsecret_and_lf_or_crlf(phase):
    line = (hello_line if phase == "hello" else ready_line)(REQUEST)
    assert len(line) <= MAX_CONTROL_BYTES
    assert parse_control_line(line, expected_request_id=REQUEST, expected_phase=phase) == phase
    assert parse_control_line(line[:-1] + b"\r\n", expected_request_id=REQUEST) == phase
    for value in (SECRET, DIRECTORY, ARGV_VALUE):
        assert value.encode() not in line


@pytest.mark.parametrize(
    "line",
    [
        b"ordinary stdout\n",
        b"@paperfact-ai-job 2 hello " + REQUEST.encode() + b"\n",
        b"@paperfact-ai-job 1 wrong " + REQUEST.encode() + b"\n",
        b"@paperfact-ai-job 1 hello " + b"b" * 32 + b"\n",
        b"x" * (MAX_CONTROL_BYTES + 1),
        hello_line(REQUEST)[:-1],
    ],
)
def test_bad_or_partial_control_lines_are_not_ready_acknowledgements(line):
    with pytest.raises(JobProtocolError):
        parse_control_line(line, expected_request_id=REQUEST)
    with pytest.raises(JobProtocolError, match="unexpected_control_phase"):
        parse_control_line(hello_line(REQUEST), expected_request_id=REQUEST, expected_phase="ready")


class BrokenStream:
    def read(self, _count):
        raise OSError(SECRET + DIRECTORY)

    def write(self, _data):
        raise OSError(SECRET + DIRECTORY)

    def flush(self):
        raise OSError(SECRET + DIRECTORY)


def test_stream_failures_and_reprs_are_redacted_and_retries_use_new_streams():
    with pytest.raises(JobProtocolError) as read_error:
        read_frame(BrokenStream(), expected_request_id=REQUEST, expected_command=COMMAND)
    with pytest.raises(JobProtocolError) as write_error:
        write_frame(BrokenStream(), intent())
    for error in (read_error.value, write_error.value):
        for value in (SECRET, DIRECTORY, ARGV_VALUE):
            assert value not in str(error) + repr(error)
    assert decode(encode_frame(intent())).command == COMMAND


@pytest.mark.parametrize("bad", [None, "not bytes", b"too many bytes"])
def test_non_binary_and_overreading_fake_streams_fail_closed(bad):
    class Source:
        def read(self, _count):
            return bad

    with pytest.raises(JobProtocolError, match="invalid_binary_stream"):
        read_frame(Source(), expected_request_id=REQUEST, expected_command=COMMAND)


@pytest.mark.parametrize("count", [None, 0, -1, True, 10**9])
def test_invalid_partial_write_counts_do_not_spin(count):
    class Sink:
        def write(self, _data):
            return count

    with pytest.raises(JobProtocolError, match="invalid_binary_stream"):
        write_frame(Sink(), intent())


def test_values_and_codec_do_not_access_configuration_files_or_providers(monkeypatch):
    import builtins

    value = intent()

    def forbidden(*_args, **_kwargs):
        pytest.fail("Pure routing core attempted file/configuration I/O")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        copy = decode(encode_frame(value))
        assert copy.routes.settings("ask").model == "task-alias"
        assert isinstance(copy, BoundJobIntent) and isinstance(copy.routes, FrozenRoutes)


@pytest.mark.parametrize("identity", [REQUEST, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"])
def test_nonsecret_request_spelling_is_preserved_and_not_normalized(identity):
    bound = routes().bind(identity, COMMAND)
    frame = encode_frame(bound)
    assert decode(frame, expected_request_id=identity).request_id == identity
    alternate = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" if identity == REQUEST else REQUEST
    with pytest.raises(JobProtocolError, match="request_mismatch"):
        decode(frame, expected_request_id=alternate)


def test_bad_magic_and_exact_maximum_payload_budget():
    with pytest.raises(JobProtocolError, match="invalid_frame_magic"):
        decode(framed(b"{}", magic=b"OTHER!"))
    payload = json.dumps(intent().to_data()).encode()
    padded = payload + b" " * (MAX_PAYLOAD_BYTES - len(payload))
    assert decode(framed(padded)).command == COMMAND
    with pytest.raises(JobProtocolError, match="budget_exceeded"):
        decode(framed(padded + b" "))


def test_flush_failure_is_secret_free_and_does_not_claim_success():
    class Sink(io.BytesIO):
        def flush(self):
            raise OSError(SECRET + DIRECTORY)

    with pytest.raises(JobProtocolError) as error:
        write_frame(Sink(), intent())
    assert error.value.code == "frame_write_failed"
    assert SECRET not in str(error.value) and DIRECTORY not in repr(error.value)
