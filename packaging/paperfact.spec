# PyInstaller build of the desktop app: run through scripts/build_app.py, which
# prepares the fonts, web assets and icons this expects to find.
#
# One folder holding two executables over the same libraries: Paperfact (windowed,
# what people open) and paperfact-cli (console, what the reader runs its
# background jobs with). On macOS the folder becomes Paperfact.app.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
ICONS = ROOT / "build" / "icons"

datas = [
    (str(ROOT / "fonts"), "fonts"),
    (str(ROOT / "vendor"), "vendor"),
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "NOTICE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    (str(ROOT / "licensing"), "licensing"),
    (str(ROOT / "build" / "dependency-licenses"), "dependency-licenses"),
    (str(ROOT / "build" / "build-info.json"), "."),
]
# Templates and scripts the package reads beside its modules (share pages, slides).
datas += collect_data_files("paper_daily")
# Features import their modules when first used, out of PyInstaller's sight.
hiddenimports = collect_submodules("paper_daily")

a = Analysis(
    [str(ROOT / "packaging" / "gui_entry.py"), str(ROOT / "packaging" / "cli_entry.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "ruff"],
    noarchive=False,
)
# Qt WebEngine links against Qt Quick, so the Qt hooks bring every QML plugin
# along: 3D, charts and the rest, ~150 MB the reader never loads. The smoke test in
# build_app.py starts the web views, so a file dropped here that was needed fails
# the build rather than a user's launch.
UNUSED_QT = ("qt63d", "qt6charts", "qt6datavisualization", "qt6graphs", "qt6quick3d")


# Qt's and Chromium's messages in every language, 54 MB; the app is read in
# Traditional Chinese, with English as Qt's fallback.
LOCALES = ("_zh_tw.", "zh-tw.", "_en.", "en-us.", "en-gb.")


def wanted(entry):
    dest = entry[0].replace("\\", "/").lower()
    name = dest.rsplit("/", 1)[-1]
    if dest.startswith("pyside6/translations/") and not any(k in name for k in LOCALES):
        return False
    return not dest.startswith("pyside6/qml/") and not name.startswith(UNUSED_QT)


a.binaries = [b for b in a.binaries if wanted(b)]
a.datas = [d for d in a.datas if wanted(d)]
pyz = PYZ(a.pure)


def scripts_for(entry):
    other = {"gui_entry", "cli_entry"} - {entry}
    return [s for s in a.scripts if s[0] not in other]


icon = {
    "win32": str(ROOT / "assets" / "paper-daily.ico"),
    "darwin": str(ICONS / "Paperfact.icns"),
}.get(sys.platform)

gui = EXE(
    pyz,
    scripts_for("gui_entry"),
    [],
    exclude_binaries=True,
    name="Paperfact",
    console=False,
    icon=icon,
    upx=False,
)
cli = EXE(
    pyz,
    scripts_for("cli_entry"),
    [],
    exclude_binaries=True,
    name="paperfact-cli",
    console=True,
    icon=icon,
    upx=False,
)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="Paperfact", upx=False)

if sys.platform == "darwin":
    from paper_daily import __version__

    app = BUNDLE(
        coll,
        name="Paperfact.app",
        icon=icon,
        bundle_identifier="io.github.puddings-world.paperfact",
        version=__version__,
        info_plist={
            "CFBundleExecutable": "Paperfact",
            "CFBundleDisplayName": "Paperfact",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.education",
        },
    )
