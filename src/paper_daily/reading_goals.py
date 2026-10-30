"""User-owned per-list research purpose, with the existing observed-edit boundary.

No AI call, automatic re-analysis, source rewrite or preference migration occurs.
"""
from contextlib import closing
from pathlib import Path

from paper_daily import research_generation as generation

TABLE = 'list_reading_goals'
MAX_GOAL = 2000


def load(database, list_id):
    """Capture an editable goal and exact list/target state; absence is observed too."""
    with closing(generation._connect(Path(database).resolve())) as conn:
        context = generation.begin_generation(
            conn, table=TABLE, owner_id=list_id, input_reader='target')
    return context


def text(context):
    if context.table != TABLE:
        raise ValueError('Expected a reading-goal observation')
    return context.target['body'] if context.target else ''


def save(context, body):
    """Publish or retain a stale draft without silently refreshing its base."""
    if context.table != TABLE or not isinstance(body, str) or len(body) > MAX_GOAL:
        raise ValueError('Reading goal must be at most 2000 characters')
    # Empty is an explicit cleared goal, not a deletion of any research content.
    if text(context) == body:
        return None
    return generation.publish_edit(context, row={
        'list_id': context.owner_id, 'body': body, 'written_at': context.data['started_at'],
    })


def describe(context):
    value = text(context).strip()
    return value if value else ''
