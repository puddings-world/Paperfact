"""Device-local evidence of a reader's explicit deletion of a synced conversation turn."""

from uuid import uuid4

from paper_daily.workspace_service import _tables


def record_reader_deletions(conn, paper, snapshots):
    """Called in the validated reader transaction, before its commit."""
    if "drive_chat_bases" not in _tables(conn):
        return
    for snapshot in snapshots:
        message = snapshot["row"].get("message_id")
        if not message:
            continue
        scopes = conn.execute(
            "SELECT b.context,b.list_id,b.op FROM drive_chat_bases b JOIN list_papers m "
            "ON m.list_id=b.list_id WHERE m.paper_id=? AND b.message=? AND b.op IS NOT NULL",
            (paper, message)
        ).fetchall()
        if not scopes:
            continue
        conn.execute("CREATE TABLE IF NOT EXISTS drive_chat_delete_actions(context,list_id,message,"
                     "paper,base,action_id,PRIMARY KEY(context,list_id,message))")
        # A restored turn can enter through the reader, a package, or another list.
        # Handle either insertion order for its local row and portable identity.
        conn.execute("CREATE TRIGGER IF NOT EXISTS withdraw_chat_delete_on_row AFTER INSERT "
                     "ON chat BEGIN DELETE FROM drive_chat_delete_actions WHERE paper=NEW.paper_id "
                     "AND message=(SELECT message_id FROM research_chat_links "
                     "WHERE local_id=NEW.id); END")
        conn.execute("CREATE TRIGGER IF NOT EXISTS withdraw_chat_delete_on_link AFTER INSERT "
                     "ON research_chat_links BEGIN DELETE FROM drive_chat_delete_actions "
                     "WHERE message=NEW.message_id AND paper=(SELECT paper_id FROM chat "
                     "WHERE id=NEW.local_id); END")
        action = str(uuid4())
        conn.executemany("INSERT OR REPLACE INTO drive_chat_delete_actions VALUES(?,?,?,?,?,?)",
                         ((context, list_id, message, paper, base, action)
                          for context, list_id, base in scopes))


def reviewed_deletions(conn, context, list_id):
    if "drive_chat_delete_actions" not in _tables(conn):
        return {}
    return {message: (paper, base, action) for message, paper, base, action in conn.execute(
        "SELECT message,paper,base,action_id FROM drive_chat_delete_actions "
        "WHERE context=? AND list_id=?", (context, list_id))}
