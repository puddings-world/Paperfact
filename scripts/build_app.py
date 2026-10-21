"""Build the installable app for the platform this runs on.

    python scripts/build_app.py              # app + installer into dist/
    python scripts/build_app.py --no-installer

Windows gives dist/Paperfact-X.Y.Z-windows-x64-setup.exe (needs Inno Setup 6),
macOS dist/Paperfact-X.Y.Z-macos-arm64.dmg, Linux dist/Paperfact-X.Y.Z-linux-x86_64.AppImage.
The release workflow runs this on each platform; see docs/releasing.md.

Before packaging, the built app is started once with no screen and an empty data
folder and must quit cleanly: a module PyInstaller missed shows up here, not on a
user's machine.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
WORK = ROOT / "build"
ICONS = WORK / "icons"
sys.path.insert(0, str(ROOT / "src"))

from paper_daily import __version__  # noqa: E402
from paper_daily.updates import ASSET_SUFFIX  # noqa: E402

# Pinned: a tagged release of appimagetool, which replaced AppImageKit's (whose
# downloads were withdrawn).
APPIMAGETOOL = (
    "https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
)
PLATFORM = "linux" if sys.platform.startswith("linux") else sys.platform


def run(*command, **kw) -> None:
    print("+", " ".join(map(str, command)), flush=True)
    subprocess.run([str(c) for c in command], check=True, cwd=kw.pop("cwd", ROOT), **kw)


def resources() -> None:
    """Fonts, web assets and icons, all downloaded or drawn by the project itself."""
    py = sys.executable
    run(py, ROOT / "scripts" / "build_notices.py")
    if not (ROOT / "fonts").is_dir() or not any((ROOT / "fonts").glob("*.ttf")):
        run(py, "-m", "paper_daily", "fonts")
    if not (ROOT / "vendor" / "web").is_dir():
        run(py, "-m", "paper_daily", "web-assets")
    run(py, ROOT / "scripts" / "make_icon.py")
    if PLATFORM != "win32":
        iconset = ICONS / "Paperfact.iconset"
        run(py, ROOT / "scripts" / "make_icon.py", "--iconset", iconset)
        if PLATFORM == "darwin":
            run("iconutil", "-c", "icns", iconset, "-o", ICONS / "Paperfact.icns")


def clean_path() -> str:
    """Only this Python and the system's own folders.

    PyInstaller resolves a DLL by searching PATH, so software installed for other
    reasons ends up inside the app: Anaconda's ICU replaced the one Windows ships,
    and the built app could not import QtCore.
    """
    keep = [Path(sys.executable).parent, Path(sys.base_prefix)]
    if PLATFORM == "win32":
        system = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        keep += [system / "System32", system]
    else:
        keep += [Path(p) for p in ("/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")]
    return os.pathsep.join(str(p) for p in keep)


def pyinstaller() -> Path:
    env = {**os.environ, "PATH": clean_path()}
    run(
        sys.executable,
        "-m",
        "PyInstaller",
        ROOT / "packaging" / "paperfact.spec",
        "--noconfirm",
        "--clean",
        "--distpath",
        DIST,
        "--workpath",
        WORK / "pyinstaller",
        env=env,
    )
    return DIST / ("Paperfact.app" if PLATFORM == "darwin" else "Paperfact")


def executables(built: Path) -> tuple[Path, Path]:
    folder = built / "Contents" / "MacOS" if PLATFORM == "darwin" else built
    ext = ".exe" if PLATFORM == "win32" else ""
    return folder / f"Paperfact{ext}", folder / f"paperfact-cli{ext}"


def smoke(built: Path) -> None:
    gui, cli = executables(built)
    out = subprocess.run([cli, "--version"], capture_output=True, text=True, check=True)
    if __version__ not in out.stdout:
        raise SystemExit(f"paperfact-cli --version said {out.stdout!r}")
    with tempfile.TemporaryDirectory() as data:
        env = {
            **os.environ,
            "PAPERFACT_DATA": data,
            "PAPERFACT_SMOKE_SECONDS": "8",
            "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen"),
        }
        done = subprocess.run([gui], env=env, timeout=180)
        log = Path(data) / "app.log"
        if done.returncode != 0:
            print(log.read_text(encoding="utf-8", errors="replace") if log.exists() else "")
            raise SystemExit(f"the built app exited with {done.returncode}")
        errors = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        if "Traceback" in errors:
            print(errors)
            raise SystemExit("the built app logged an error on start")
    print("smoke test passed", flush=True)


def artifact_name() -> str:
    return f"Paperfact-{__version__}{ASSET_SUFFIX[PLATFORM]}"


def find_iscc() -> str | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    found = os.environ.get("ISCC") or shutil.which("ISCC")
    return found or next((str(p) for p in candidates if p.exists()), None)


def windows_installer(built: Path) -> Path:
    iscc = find_iscc()
    if iscc is None:
        raise SystemExit("the installer needs Inno Setup 6: winget install JRSoftware.InnoSetup")
    run(
        iscc,
        f"/DAppVersion={__version__}",
        f"/DSourceDir={built}",
        f"/DOutputDir={DIST}",
        ROOT / "packaging" / "windows" / "paperfact.iss",
    )
    return DIST / artifact_name()


def mac_dmg(built: Path) -> Path:
    stage = WORK / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    run("ditto", built, stage / built.name)
    (stage / "Applications").symlink_to("/Applications")
    out = DIST / artifact_name()
    out.unlink(missing_ok=True)
    run(
        "hdiutil",
        "create",
        "-volname",
        "Paperfact",
        "-srcfolder",
        stage,
        "-ov",
        "-format",
        "UDZO",
        out,
    )
    return out


def linux_appimage(built: Path) -> Path:
    appdir = WORK / "Paperfact.AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(built, appdir / "usr" / "lib" / "paperfact", symlinks=True)
    apprun = appdir / "AppRun"
    apprun.write_text(
        '#!/bin/sh\nhere="$(dirname "$(readlink -f "$0")")"\n'
        'exec "$here/usr/lib/paperfact/Paperfact" "$@"\n',
        encoding="utf-8",
    )
    apprun.chmod(apprun.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (appdir / "paperfact.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Paperfact\n"
        "Comment=Read papers, take notes, and explore research\n"
        "Exec=Paperfact\nIcon=paperfact\nCategories=Education;Science;Office;\nTerminal=false\n",
        encoding="utf-8",
    )
    shutil.copy(ICONS / "Paperfact.iconset" / "icon_256x256.png", appdir / "paperfact.png")
    tool = WORK / "appimagetool.AppImage"
    if not tool.exists():
        urllib.request.urlretrieve(APPIMAGETOOL, tool)
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    out = DIST / artifact_name()
    out.unlink(missing_ok=True)
    # Extract-and-run: build machines often have no FUSE to mount the tool itself.
    run(tool, "--appimage-extract-and-run", appdir, out, env={**os.environ, "ARCH": "x86_64"})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-installer", action="store_true", help="stop after the app folder")
    args = parser.parse_args()
    tag = os.environ.get("GITHUB_REF_NAME", "")
    if os.environ.get("GITHUB_REF_TYPE") == "tag" and tag != f"v{__version__}":
        raise SystemExit(f"tag {tag} does not match the version in the code ({__version__})")
    resources()
    built = pyinstaller()
    smoke(built)
    if args.no_installer:
        return 0
    package = {"win32": windows_installer, "darwin": mac_dmg, "linux": linux_appimage}[PLATFORM]
    out = package(built)
    print(f"built {out} ({out.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
