"""A source checkout and an installed build find their files and run their jobs
differently; these pin both."""

from pathlib import Path

from paper_daily import config, runtime


def test_each_platform_keeps_app_data_in_its_own_place():
    home = Path("/home/u")
    assert runtime.user_data_dir("win32", {"APPDATA": r"C:\Users\u\AppData\Roaming"}, home) == (
        Path(r"C:\Users\u\AppData\Roaming") / "Paperfact"
    )
    assert runtime.user_data_dir("darwin", {}, home) == (
        home / "Library" / "Application Support" / "Paperfact"
    )
    assert runtime.user_data_dir("linux", {}, home) == home / ".local/share/Paperfact"
    assert runtime.user_data_dir("linux", {"XDG_DATA_HOME": "/data"}, home) == Path(
        "/data/Paperfact"
    )


def test_a_checkout_runs_its_jobs_through_python():
    assert runtime.cli_command("survey", "l1", frozen=False, executable="/py") == [
        "/py",
        "-m",
        "paper_daily",
        "survey",
        "l1",
    ]


def test_an_installed_build_runs_its_jobs_through_its_console_twin():
    command = runtime.cli_command("survey", "l1", frozen=True, executable="/opt/P/Paperfact")
    assert Path(command[0]).parent == Path("/opt/P")
    assert Path(command[0]).stem == "paperfact-cli"
    assert command[1:] == ["survey", "l1"]


def test_the_login_path_comes_first_and_nothing_is_lost():
    sep = runtime.os.pathsep
    merged = runtime.merged_path(
        sep.join(["/usr/bin", "/bin"]), sep.join(["/opt/homebrew/bin", "/usr/bin"])
    )
    assert merged.split(sep) == ["/opt/homebrew/bin", "/usr/bin", "/bin"]
    assert runtime.merged_path("/usr/bin", None) == "/usr/bin"


def test_an_installed_build_keeps_data_outside_the_app(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "user_data_dir", lambda env: tmp_path / "appdata")
    assert runtime.data_dir({}, frozen=True) == tmp_path / "appdata"
    assert runtime.data_dir({}, frozen=False) == runtime.bundle_root() / "data"
    assert runtime.data_dir({"PAPERFACT_DATA": str(tmp_path / "x")}, frozen=True) == tmp_path / "x"


def test_no_contact_address_is_built_in():
    assert (
        config.user_agent("")
        == f"Paperfact/{config.__version__} (+https://github.com/puddings-world/Paperfact)"
    )
    assert "mailto:me@example.org" in config.user_agent("me@example.org")


def test_a_checkout_env_file_sets_what_the_environment_leaves_unset(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\ufeff# where my papers live\n"
        "PAPERFACT_DATA=D:\Paperfact-data\n"
        "export PAPERFACT_EMAIL = 'me@example.org'\n"
        'S2_API_KEY="abc=def"\n'
        "\n"
        "not a setting\n",
        encoding="utf-8",
    )
    assert runtime.read_env_file(env_file) == {
        "PAPERFACT_DATA": "D:\Paperfact-data",
        "PAPERFACT_EMAIL": "me@example.org",
        "S2_API_KEY": "abc=def",
    }
    env = {"S2_API_KEY": "from the shell"}
    runtime.load_env_file(env, frozen=False, path=env_file)
    assert env["S2_API_KEY"] == "from the shell"
    assert runtime.data_dir(env, frozen=False) == Path("D:\Paperfact-data")
    # An installed build ignores any .env it might find; a missing file is no error.
    untouched = {}
    runtime.load_env_file(untouched, frozen=True, path=env_file)
    runtime.load_env_file(untouched, frozen=False, path=tmp_path / "absent")
    assert untouched == {}
