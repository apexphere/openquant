from typing import Optional
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from openquant.helpers import get_os
from openquant.services import auth as authenticator
from openquant.services.lsp import LSP_DEFAULT_PORT

router = APIRouter(prefix='/lsp-config', tags=['LSP Configuration'])

@router.get("")
def get_lsp_config(authorization: Optional[str] = Header(None))->JSONResponse:
    if not authenticator.is_valid_token(authorization):
        return authenticator.unauthorized_response()

    from openquant.services.env import ENV_VALUES

    # Check if formatting is available on the current platform
    # Formatting is only available on non-windows platforms
    isFormattingAvailable = get_os() != 'windows'
    
    return JSONResponse(
        {'ws_port': ENV_VALUES['LSP_PORT'] if 'LSP_PORT' in ENV_VALUES else LSP_DEFAULT_PORT,
         'ws_path':'/lsp',
         'is_formatting_available': isFormattingAvailable}, status_code=200)