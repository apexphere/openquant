import peewee
import json
from openquant.services.db import database
import openquant.helpers as jh


if database.is_closed():
    database.open_connection()


class ResearchNote(peewee.Model):
    id = peewee.UUIDField(primary_key=True)

    # Link to backtest or optimization session (optional)
    session_id = peewee.UUIDField(null=True, index=True)
    session_type = peewee.CharField(null=True)  # 'backtest' | 'optimization'

    # Strategy-level grouping (denormalized for fast lookup)
    strategy_name = peewee.CharField(index=True)

    # Iteration tracking
    round_number = peewee.IntegerField(null=True)

    # Structured research fields
    hypothesis = peewee.TextField(null=True)
    result_summary = peewee.TextField(null=True)
    regime_quality = peewee.TextField(null=True)
    diagnosis = peewee.TextField(null=True)
    next_steps = peewee.TextField(null=True)

    # Tags as JSON array
    tags = peewee.TextField(null=True)

    # Authorship: 'human' or agent name
    author = peewee.CharField(null=True)

    # Timestamps
    created_at = peewee.BigIntegerField()
    updated_at = peewee.BigIntegerField()

    class Meta:
        from openquant.services.db import database

        database = database.db
        indexes = (
            (('id',), True),
            (('session_id',), False),
            (('strategy_name',), False),
            (('created_at',), False),
        )

    def __init__(self, attributes: dict = None, **kwargs) -> None:
        peewee.Model.__init__(self, attributes=attributes, **kwargs)

        if attributes is None:
            attributes = {}

        for a, value in attributes.items():
            setattr(self, a, value)

    @property
    def tags_json(self):
        if not self.tags:
            return []
        return json.loads(self.tags)

    @tags_json.setter
    def tags_json(self, tags_list):
        self.tags = json.dumps(tags_list) if tags_list else None


# if database is open, create the table
if database.is_open():
    ResearchNote.create_table()

# # # # # # # # # # # # # # # # # # # # # # # # # # #
# # # # # # # # # DB FUNCTIONS # # # # # # # # #
# # # # # # # # # # # # # # # # # # # # # # # # # # #


def store_research_note(
    strategy_name: str,
    session_id: str = None,
    session_type: str = None,
    round_number: int = None,
    hypothesis: str = None,
    result_summary: str = None,
    regime_quality: str = None,
    diagnosis: str = None,
    next_steps: str = None,
    tags: list = None,
    author: str = 'human',
) -> str:
    note_id = jh.generate_unique_id()
    d = {
        'id': note_id,
        'strategy_name': strategy_name,
        'session_id': session_id,
        'session_type': session_type,
        'round_number': round_number,
        'hypothesis': hypothesis,
        'result_summary': result_summary,
        'regime_quality': regime_quality,
        'diagnosis': diagnosis,
        'next_steps': next_steps,
        'tags': json.dumps(tags) if tags else None,
        'author': author,
        'created_at': jh.now_to_timestamp(True),
        'updated_at': jh.now_to_timestamp(True),
    }
    ResearchNote.insert(**d).execute()
    return note_id


def get_research_note_by_id(id: str):
    try:
        return ResearchNote.get(ResearchNote.id == id)
    except ResearchNote.DoesNotExist:
        return None


def get_research_notes_by_session(session_id: str) -> list:
    return list(
        ResearchNote.select()
        .where(ResearchNote.session_id == session_id)
        .order_by(ResearchNote.created_at.asc())
    )


def get_research_notes_by_strategy(strategy_name: str, limit: int = 50, offset: int = 0) -> list:
    return list(
        ResearchNote.select()
        .where(ResearchNote.strategy_name == strategy_name)
        .order_by(ResearchNote.created_at.asc())
        .limit(limit)
        .offset(offset)
    )


def get_strategies_with_notes() -> list:
    """Returns list of strategy names that have research notes, with counts."""
    query = (
        ResearchNote.select(
            ResearchNote.strategy_name,
            peewee.fn.COUNT(ResearchNote.id).alias('note_count'),
            peewee.fn.MAX(ResearchNote.updated_at).alias('last_updated'),
        )
        .group_by(ResearchNote.strategy_name)
        .order_by(peewee.fn.MAX(ResearchNote.updated_at).desc())
    )
    return [
        {
            'strategy_name': row.strategy_name,
            'note_count': row.note_count,
            'last_updated': row.last_updated,
        }
        for row in query
    ]


def update_research_note(id: str, **fields) -> None:
    d = {'updated_at': jh.now_to_timestamp(True)}

    for key in ('hypothesis', 'result_summary', 'regime_quality', 'diagnosis',
                'next_steps', 'author', 'round_number'):
        if key in fields and fields[key] is not None:
            d[key] = fields[key]

    if 'tags' in fields:
        d['tags'] = json.dumps(fields['tags']) if fields['tags'] else None

    ResearchNote.update(**d).where(ResearchNote.id == id).execute()


def delete_research_note(id: str) -> bool:
    try:
        ResearchNote.delete().where(ResearchNote.id == id).execute()
        return True
    except Exception:
        return False


def get_next_round_number(strategy_name: str) -> int:
    """Returns the next round number for a strategy (max + 1, or 1 if none)."""
    result = (
        ResearchNote.select(peewee.fn.MAX(ResearchNote.round_number))
        .where(ResearchNote.strategy_name == strategy_name)
        .scalar()
    )
    return (result or 0) + 1
