from typing import Optional, List
from fastapi import APIRouter, Header, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from openquant.services import auth as authenticator
from openquant.services.trade_diagnostics import diagnose_session
from openquant.services.timeframe_analysis import analyze_timeframes


router = APIRouter(prefix="/diagnose", tags=["Diagnose"])


class DiagnoseRequestJson(BaseModel):
    top_n: int = 5


class AnalyzeTimeframeRequestJson(BaseModel):
    exchange: str = 'Bybit USDT Perpetual'
    symbol: str = 'BTC-USDT'
    start_date: str
    finish_date: str
    indicator: str = 'bb'
    period: int = 20
    timeframes: Optional[List[str]] = None
    bb_mult: float = 2.0


@router.post("/session/{session_id}")
def diagnose(
    session_id: str,
    request_json: DiagnoseRequestJson = Body(default=DiagnoseRequestJson()),
    authorization: Optional[str] = Header(None),
):
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    try:
        result = diagnose_session(session_id, top_n=request_json.top_n)
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=404)


@router.post("/analyze-timeframe")
def analyze_timeframe(
    request_json: AnalyzeTimeframeRequestJson,
    authorization: Optional[str] = Header(None),
):
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    try:
        result = analyze_timeframes(
            exchange=request_json.exchange,
            symbol=request_json.symbol,
            start_date=request_json.start_date,
            finish_date=request_json.finish_date,
            indicator=request_json.indicator,
            period=request_json.period,
            timeframes=request_json.timeframes,
            bb_mult=request_json.bb_mult,
        )
        return JSONResponse(result)
    except Exception as e:
        import traceback
        return JSONResponse({
            'error': str(e),
            'traceback': traceback.format_exc(),
        }, status_code=500)
