"""Pure captured routing values; no live configuration or providers."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from paper_daily.ai_job_intent import (
    MAX_ARGUMENTS,
    MAX_PROFILES,
    MAX_ROUTES,
    MAX_TEXT_BYTES,
    BoundJobIntent,
    FrozenRoutes,
    JobIntentError,
)
from paper_daily.ai_types import Settings

SECRET = "synthetic-secret-do-not-echo"
DIRECTORY = "/private/account-context-not-for-repr"
ARGV_VALUE = "/private/research-list-not-for-repr"
REQUEST = "a" * 32


def configured():
    return Settings(
        "openai",
        model=None,
        api_key=SECRET,
        base_url="https://example.invalid/private-endpoint",
        profile="captured",
        api_key_env="SYNTHETIC_KEY",
        max_tokens=1234,
        token_parameter="max_tokens",
        requires_key=False,
        isolated=True,
        account_id="b" * 32,
        cli_home=DIRECTORY + "/native",
    )


def routes():
    return FrozenRoutes(
        Settings("none"),
        {"survey": configured(), "ask": replace(configured(), model="task-alias")},
        profiles={"explicit": replace(configured(), model="profile-model")},
        account_directory=DIRECTORY,
    )


def test_all_resolved_fields_and_none_model_are_preserved_without_inventing_versions():
    value = routes()
    assert value.settings("survey") == configured()
    assert value.settings().backend == "none"
    assert value.settings("survey").model is None
    assert value.settings("ask").model == "task-alias"
    assert value.settings("ask", profile="explicit").model == "profile-model"
    assert set(value.to_data()["tasks"]["survey"]) == {item.name for item in fields(Settings)}
    assert value.account_directory == DIRECTORY
    assert value.task_names == ("ask", "survey") and value.profile_names == ("explicit",)


def test_settings_inputs_and_all_outputs_are_defensive_primitive_copies():
    cfg = configured()
    original = {"survey": cfg}
    value = FrozenRoutes(cfg, original)
    original["survey"] = Settings("codex", model="changed")
    object.__setattr__(cfg, "api_key", "changed-after-capture")
    assert value.settings("survey").api_key == SECRET
    copy = value.settings("survey")
    object.__setattr__(copy, "model", "changed-returned-object")
    data = value.to_data()
    data["tasks"]["survey"]["api_key"] = "changed-returned-data"
    data["tasks"].clear()
    assert value.settings("survey").api_key == SECRET
    assert value.settings("survey").model is None
    with pytest.raises(FrozenInstanceError):
        value._tasks = ()


def test_force_is_bound_only_after_confirmation_without_recapturing_routes():
    captured = routes()
    argv = ["survey", ARGV_VALUE]
    first = captured.bind(REQUEST, argv)
    argv.append("--force")
    confirmed = BoundJobIntent(captured, REQUEST, argv)
    assert first.command == ("survey", ARGV_VALUE)
    assert confirmed.command == ("survey", ARGV_VALUE, "--force")
    assert confirmed.routes.settings("survey") == configured()
    detached = confirmed.routes
    object.__setattr__(detached, "_tasks", ())
    assert confirmed.routes.settings("survey") == configured()
    encoded = confirmed.to_data()
    encoded["command"].clear()
    encoded["routes"]["tasks"]["survey"]["api_key"] = "not-retained"
    assert (
        confirmed.command[-1] == "--force" and confirmed.routes.settings("survey").api_key == SECRET
    )


@pytest.mark.parametrize(
    "task,profile,code",
    [
        ("missing", None, "undeclared_task"),
        ("survey", "missing", "undeclared_profile"),
        ("missing", "explicit", "undeclared_task"),
        (False, None, "undeclared_task"),
    ],
)
def test_undeclared_tasks_profiles_never_fall_back_to_defaults_or_environment(
    monkeypatch,
    task,
    profile,
    code,
):
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-current-key")
    with pytest.raises(JobIntentError) as error:
        routes().settings(task, profile=profile)
    assert error.value.code == code


@pytest.mark.parametrize(
    "field,value",
    [
        ("backend", "auto"),
        ("backend", "Bad Backend"),
        ("model", []),
        ("api_key", {}),
        ("base_url", 1),
        ("profile", False),
        ("api_key_env", "invalid-name"),
        ("max_tokens", True),
        ("max_tokens", 0),
        ("token_parameter", []),
        ("requires_key", 1),
        ("isolated", None),
        ("account_id", "../outside"),
        ("cli_home", [DIRECTORY]),
        ("model", "bad\0text"),
        ("model", "\ud800"),
    ],
)
def test_invalid_settings_types_fail_closed_with_no_value_in_errors(field, value):
    cfg = replace(configured(), **{field: value})
    with pytest.raises(JobIntentError) as error:
        FrozenRoutes(cfg, {})
    assert SECRET not in str(error.value) + repr(error.value)
    assert DIRECTORY not in str(error.value) + repr(error.value)


def test_repr_and_exception_text_never_disclose_keys_paths_or_argv():
    captured = routes()
    intent = captured.bind(REQUEST, ["survey", ARGV_VALUE])
    text = repr(captured) + str(captured) + repr(intent) + str(intent)
    for secret in (SECRET, DIRECTORY, ARGV_VALUE, "private-endpoint", "SYNTHETIC_KEY"):
        assert secret not in text
    error = JobIntentError(SECRET)
    assert str(error) == "invalid_intent" and SECRET not in repr(error)


@pytest.mark.parametrize("mutation", ["extra", "missing", "bad-tasks", "bad-profile", "field"])
def test_closed_route_wire_objects_do_not_accept_extensions_or_missing_fields(mutation):
    data = routes().to_data()
    if mutation == "extra":
        data[SECRET] = "unknown"
    elif mutation == "missing":
        del data["account_directory"]
    elif mutation == "bad-tasks":
        data["tasks"] = []
    elif mutation == "bad-profile":
        data["profiles"] = {"../outside": configured().__dict__}
    else:
        data["tasks"]["survey"][SECRET] = True
    with pytest.raises(JobIntentError) as error:
        FrozenRoutes.from_data(data)
    assert SECRET not in str(error.value) + repr(error.value)


def test_declared_map_text_and_aggregate_sizes_are_bounded():
    with pytest.raises(JobIntentError, match="budget_exceeded"):
        FrozenRoutes(
            Settings("none"), {f"task_{i}": Settings("none") for i in range(MAX_ROUTES + 1)}
        )
    with pytest.raises(JobIntentError, match="budget_exceeded"):
        FrozenRoutes(
            Settings("none"),
            {},
            profiles={f"profile{i}": Settings("none") for i in range(MAX_PROFILES + 1)},
        )
    with pytest.raises(JobIntentError, match="budget_exceeded"):
        FrozenRoutes(replace(configured(), api_key="x" * (MAX_TEXT_BYTES + 1)), {})
    with pytest.raises(JobIntentError, match="budget_exceeded"):
        FrozenRoutes(
            Settings("none"),
            {f"task_{i}": replace(configured(), api_key="x" * MAX_TEXT_BYTES) for i in range(20)},
        )


@pytest.mark.parametrize(
    "request_id,command",
    [
        ("not-a-request", ["survey"]),
        (REQUEST, "survey"),
        (REQUEST, []),
        (REQUEST, ["survey", "bad\0arg"]),
        (REQUEST, ["/program/path"]),
        (REQUEST, ["survey"] * (MAX_ARGUMENTS + 1)),
    ],
)
def test_binding_rejects_malformed_request_and_command_without_echo(request_id, command):
    with pytest.raises(JobIntentError) as error:
        BoundJobIntent(routes(), request_id, command)
    assert ARGV_VALUE not in str(error.value) + repr(error.value)


def test_unknown_job_version_missing_fields_and_detached_round_trip():
    intent = routes().bind(REQUEST, ["survey", ARGV_VALUE, "--force"])
    copy = BoundJobIntent.from_data(intent.to_data())
    assert copy.command == intent.command and copy.routes.settings("ask") == intent.routes.settings(
        "ask"
    )
    for version in (True, 0, 2, "1"):
        data = intent.to_data()
        data["version"] = version
        with pytest.raises(JobIntentError, match="unsupported_version"):
            BoundJobIntent.from_data(data)
    data = intent.to_data()
    del data["routes"]
    with pytest.raises(JobIntentError):
        BoundJobIntent.from_data(data)


def test_two_concurrent_fake_jobs_have_no_shared_route_mutation():
    first, second = (
        routes(),
        FrozenRoutes(Settings("none"), {"survey": Settings("codex", model="B")}),
    )

    def selected(item):
        route, expected = item
        output = route.settings("survey")
        object.__setattr__(output, "model", "caller-edited-copy")
        return route.settings("survey").model == expected

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(selected, [(first, None), (second, "B")] * 20))
