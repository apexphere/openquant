from typing import Optional
from fastapi import APIRouter, Header, Body
from fastapi.responses import JSONResponse
from openquant.services import auth as authenticator
from openquant.services.web import (
    CreateResearchNoteRequestJson,
    UpdateResearchNoteRequestJson,
    GetResearchNotesRequestJson,
)
from openquant.models.ResearchNote import (
    store_research_note,
    get_research_note_by_id,
    get_research_notes_by_session,
    get_research_notes_by_strategy,
    get_strategies_with_notes,
    get_next_round_number,
    update_research_note,
    delete_research_note,
)
from openquant.models.BacktestSession import get_backtest_session_by_id
from openquant.models.OptimizationSession import get_optimization_session_by_id
from openquant.services.transformers import get_research_note


router = APIRouter(prefix="/research-notes", tags=["Research Notes"])


@router.post("")
def create_research_note(
    request_json: CreateResearchNoteRequestJson,
    authorization: Optional[str] = Header(None),
):
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    strategy_name = request_json.strategy_name
    session_type = request_json.session_type

    # Auto-resolve strategy_name from session if not provided
    if not strategy_name and request_json.session_id:
        session = get_backtest_session_by_id(request_json.session_id)
        if session:
            strategy_name = session.strategy_name
            session_type = 'backtest'
        else:
            session = get_optimization_session_by_id(request_json.session_id)
            if session:
                strategy_name = _get_strategy_name_from_optimization(session)
                session_type = 'optimization'

    if not strategy_name:
        return JSONResponse(
            {'error': 'strategy_name is required (or provide a valid session_id to auto-resolve)'},
            status_code=400,
        )

    # Auto-assign round number if not provided
    round_number = request_json.round_number
    if round_number is None:
        round_number = get_next_round_number(strategy_name)

    note_id = store_research_note(
        strategy_name=strategy_name,
        session_id=request_json.session_id,
        session_type=session_type,
        round_number=round_number,
        hypothesis=request_json.hypothesis,
        result_summary=request_json.result_summary,
        regime_quality=request_json.regime_quality,
        diagnosis=request_json.diagnosis,
        next_steps=request_json.next_steps,
        tags=request_json.tags,
        author=request_json.author,
    )

    note = get_research_note_by_id(note_id)
    return JSONResponse({
        'message': 'Research note created',
        'note': get_research_note(note),
    })


@router.post("/session/{session_id}")
def get_notes_by_session(
    session_id: str,
    authorization: Optional[str] = Header(None),
):
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    notes = get_research_notes_by_session(session_id)
    return JSONResponse({
        'notes': [get_research_note(n) for n in notes],
    })


@router.post("/strategy/{strategy_name}")
def get_notes_by_strategy(
    strategy_name: str,
    request_json: GetResearchNotesRequestJson = Body(default=GetResearchNotesRequestJson()),
    authorization: Optional[str] = Header(None),
):
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    notes = get_research_notes_by_strategy(
        strategy_name,
        limit=request_json.limit,
        offset=request_json.offset,
    )
    return JSONResponse({
        'notes': [get_research_note(n) for n in notes],
        'strategy_name': strategy_name,
    })


@router.post("/strategies")
def get_strategies(
    authorization: Optional[str] = Header(None),
):
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    strategies = get_strategies_with_notes()
    return JSONResponse({
        'strategies': strategies,
    })


@router.post("/{note_id}/details")
def get_note_details(
    note_id: str,
    authorization: Optional[str] = Header(None),
):
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    note = get_research_note_by_id(note_id)
    if not note:
        return JSONResponse({'error': 'Research note not found'}, status_code=404)

    return JSONResponse({
        'note': get_research_note(note),
    })


@router.post("/{note_id}/update")
def update_note(
    note_id: str,
    request_json: UpdateResearchNoteRequestJson,
    authorization: Optional[str] = Header(None),
):
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    note = get_research_note_by_id(note_id)
    if not note:
        return JSONResponse({'error': 'Research note not found'}, status_code=404)

    fields = {}
    for key in ('hypothesis', 'result_summary', 'regime_quality', 'diagnosis',
                'next_steps', 'author', 'round_number'):
        value = getattr(request_json, key, None)
        if value is not None:
            fields[key] = value

    if request_json.tags is not None:
        fields['tags'] = request_json.tags

    update_research_note(note_id, **fields)

    updated_note = get_research_note_by_id(note_id)
    return JSONResponse({
        'message': 'Research note updated',
        'note': get_research_note(updated_note),
    })


@router.post("/{note_id}/delete")
def delete_note(
    note_id: str,
    authorization: Optional[str] = Header(None),
):
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    note = get_research_note_by_id(note_id)
    if not note:
        return JSONResponse({'error': 'Research note not found'}, status_code=404)

    delete_research_note(note_id)
    return JSONResponse({'message': 'Research note deleted'})


def _get_strategy_name_from_optimization(session) -> str:
    """Extract strategy name from optimization session state."""
    if session.state:
        import json
        state = json.loads(session.state) if isinstance(session.state, str) else session.state
        routes = state.get('form', {}).get('routes', [])
        if routes:
            return routes[0].get('strategy', '')
    return ''
