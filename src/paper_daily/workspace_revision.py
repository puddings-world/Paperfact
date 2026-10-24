"""A transaction-scoped invalidation counter, independent of the writer API.

Legacy CLI, bundle imports and ordinary SQLite writers all execute these triggers.
The counter is bounded storage; rolling back a transaction rolls it back too.
Only list-visible research invalidates lists, not account polling or UI settings.
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_revision (
    id INTEGER PRIMARY KEY CHECK(id=1),
    revision INTEGER NOT NULL
);
INSERT OR IGNORE INTO workspace_revision(id,revision) VALUES(1,0);
CREATE INDEX IF NOT EXISTS idx_list_papers_paper ON list_papers(paper_id);
"""

# These identifiers are fixed source constants, never caller-supplied SQL.
for table, key in (
    ("lists", None),
    ("list_papers", None),
    ("papers", "id"),
    ("dives", "paper_id"),
    ("close_readings", "paper_id"),
    ("cites", "paper_id"),
    ("pins", "paper_id"),
    ("resources", "paper_id"),
):
    for action in ("INSERT", "UPDATE", "DELETE"):
        row = "OLD" if action == "DELETE" else "NEW"
        condition = (
            f"WHEN EXISTS(SELECT 1 FROM list_papers WHERE paper_id={row}.{key})" if key else ""
        )
        SCHEMA += f"""
CREATE TRIGGER IF NOT EXISTS paperfact_revision_{table}_{action.lower()}
AFTER {action} ON {table} {condition}
BEGIN
    UPDATE workspace_revision SET revision=revision+1 WHERE id=1;
END;
"""

for action in ("INSERT", "UPDATE", "DELETE"):
    row = "OLD" if action == "DELETE" else "NEW"
    SCHEMA += f"""
CREATE TRIGGER IF NOT EXISTS paperfact_revision_kv_{action.lower()}
AFTER {action} ON kv
WHEN {row}.key='lists.order' OR {row}.key LIKE 'followups.checked.%'
     OR {row}.key LIKE 'analyze.failed.pdf.%'
BEGIN
    UPDATE workspace_revision SET revision=revision+1 WHERE id=1;
END;
"""
