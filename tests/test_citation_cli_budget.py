"""Explicit CLI cost limits reach the shared citation operation."""

import pytest

from paper_daily import cites, cli


@pytest.mark.parametrize("value", [None, 0, 1, 2])
def test_cli_forwards_explicit_completion_limit(monkeypatch, value):
    command = ["cites", "paper"]
    if value is not None:
        command.extend(["--completion-calls", str(value)])
    args = cli.build_parser().parse_args(command)
    calls = []

    def run(paper, **options):
        calls.append((paper, options["max_additional_calls"]))
        return 0

    monkeypatch.setattr(cites, "analyse", run)
    assert args.func(args) == 1
    assert calls == [("paper", value or 0)]


@pytest.mark.parametrize("value", ["-1", "3", "auto", "1.5"])
def test_invalid_cli_limit_is_rejected_before_execution(value):
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["cites", "paper", "--completion-calls", value])
    assert exc.value.code == 2
