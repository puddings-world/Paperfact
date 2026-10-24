"""The installed app's console twin: every `paperfact` subcommand.

The reader starts its background work (analysis, surveys, adding papers) through
this executable, and it is the command line for anyone who wants one.
"""

from paper_daily.integration_entry import main

raise SystemExit(main())
