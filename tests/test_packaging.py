"""The Windows installer script only names files the build machine will have."""

import re
from pathlib import Path

ISS = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "paperfact.iss"


def test_restart_manager_uses_the_compilers_supported_enum():
    # Unlike CreateUninstallRegKey, this directive does not accept a scripted
    # boolean expression. Acceptance installs override it with /NOCLOSEAPPLICATIONS.
    value = re.search(r'^CloseApplications=(.+)$', ISS.read_text(encoding="utf-8"),
                      re.MULTILINE).group(1)
    assert value.strip() in {"yes", "no", "force"}


def test_installer_languages_not_shipped_with_inno_setup_are_in_the_repo():
    files = re.findall(r'MessagesFile:\s*"([^"]+)"', ISS.read_text(encoding="utf-8"))
    assert files
    for name in files:
        if name.startswith("compiler:"):
            # Only Default.isl sits at the compiler root on every install; the
            # Languages folder holds the official translations, and Chinese is not one.
            assert name == "compiler:Default.isl", name
        else:
            assert (ISS.parent / name).is_file(), name
