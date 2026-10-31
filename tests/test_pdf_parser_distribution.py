"""A clean checkout must contain exactly the pinned offline parser dependency."""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "mobile/vendor/pdfjs-6.4.299/"
PINNED = {
    "pdf.mjs": ("630de0bd0092cf2e9d46a23c68596b736699035e08cce4e9c85537c8eba0fc8e", 1069549),
    "pdf.worker.mjs": ("bb422f60804477de4a0b09091d8347a916a387755ed1cbad24ccaec1d09c78bf", 2418244),
    "LICENSE": ("0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594", 10174),
}


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    return root


def ignored(checkout, names):
    return subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"],
        input=b"\0".join(name.encode("utf-8") for name in names) + b"\0",
        cwd=checkout, capture_output=True,
    )


def test_clean_checkout_keeps_parser_worker_license_and_provenance(checkout):
    names = [PREFIX + name for name in (*PINNED, "provenance.json")]
    for name in names:
        path = checkout / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    result = ignored(checkout, names)
    assert result.returncode == 1, result.stdout
    assert result.stdout == b""


@pytest.mark.parametrize("name", [
    "vendor/unpinned-download.js",
    "mobile/vendor/unpinned/extra.mjs",
    PREFIX + "unreviewed-extra.mjs",
])
def test_parser_exception_does_not_include_unreviewed_downloads(checkout, name):
    result = ignored(checkout, [name])
    assert result.returncode == 0
    assert result.stdout == name.encode("utf-8") + b"\0"


def test_offline_parser_bytes_and_license_match_the_pinned_release():
    folder = ROOT / PREFIX
    provenance = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["version"] == "6.4.299"
    assert provenance["license"] == "Apache-2.0"
    assert provenance["archive_sha256"] == (
        "c894bce53b2f4c3e13141e088c89cc051a1f7118ba4a2c02ec058798ae1303d1"
    )
    assert {item["path"] for item in provenance["files"]} == set(PINNED)
    for item in provenance["files"]:
        digest, size = PINNED[item["path"]]
        data = (folder / item["path"]).read_bytes()
        assert (hashlib.sha256(data).hexdigest(), len(data)) == (digest, size)
        assert (item["sha256"], item["bytes"]) == (digest, size)


def test_pinned_parser_bytes_survive_a_windows_style_git_checkout(checkout):
    (checkout / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    names = [PREFIX + name for name in (*PINNED, "provenance.json")]
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    subprocess.run(
        ["git", "-c", "core.autocrlf=false", "add", "--",
         ".gitattributes", ".gitignore", *names],
        cwd=checkout, check=True, capture_output=True,
    )
    restored = checkout / "windows-checkout"
    restored.mkdir()
    assert restored.resolve().is_relative_to(checkout.resolve())
    subprocess.run(
        ["git", "-c", "core.autocrlf=true", "checkout-index", "-a", "-f",
         "--prefix=" + restored.as_posix() + "/"],
        cwd=checkout, check=True, capture_output=True,
    )
    for name in names:
        assert (restored / name).read_bytes() == (ROOT / name).read_bytes(), name
    for name, (digest, size) in PINNED.items():
        data = (restored / PREFIX / name).read_bytes()
        assert (hashlib.sha256(data).hexdigest(), len(data)) == (digest, size)
