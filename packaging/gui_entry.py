"""The installed app's double-click entry: the desktop reader, with the `app` flags."""

import os
import sys

# A windowed executable on Windows starts with no stdout or stderr at all, and the
# first print() anywhere in the reader would raise.
for name in ("stdout", "stderr"):
    if getattr(sys, name) is None:
        setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115

from paper_daily.integration_entry import main  # noqa: E402

raise SystemExit(main(["app", *sys.argv[1:]]))
