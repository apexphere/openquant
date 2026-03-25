import os
import warnings
from contextlib import asynccontextmanager
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openquant.services.web import fastapi_app
import openquant.helpers as jh

# import cli to register the routes. Do NOT remove this import.
from openquant.cli import cli


# to silent stupid pandas warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

# get the jesse directory
JESSE_DIR = os.path.dirname(os.path.abspath(__file__))

# define lifespan (replaces deprecated @on_event("shutdown"))
@asynccontextmanager
async def lifespan(app):
    yield
    from openquant.services.db import database
    database.close_connection()
    from openquant.services.lsp import terminate_lsp_server
    terminate_lsp_server()

fastapi_app.router.lifespan_context = lifespan

# load homepage
@fastapi_app.get("/")
async def index():
    return FileResponse(f"{JESSE_DIR}/static/index.html")






# # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Routes
# # # # # # # # # # # # # # # # # # # # # # # # # # # #
from openquant.controllers.websocket_controller import router as websocket_router
from openquant.controllers.optimization_controller import router as optimization_router
from openquant.controllers.monte_carlo_controller import router as monte_carlo_router
from openquant.controllers.exchange_controller import router as exchange_router
from openquant.controllers.backtest_controller import router as backtest_router
from openquant.controllers.candles_controller import router as candles_router
from openquant.controllers.strategy_controller import router as strategy_router
from openquant.controllers.auth_controller import router as auth_router
from openquant.controllers.config_controller import router as config_router
from openquant.controllers.notification_controller import router as notification_router
from openquant.controllers.system_controller import router as system_router
from openquant.controllers.file_controller import router as file_router
from openquant.controllers.lsp_controller import router as lsp_router
from openquant.controllers.closed_trade_controller import router as closed_trade_router
from openquant.controllers.order_controller import router as order_router
from openquant.controllers.tabs_controller import router as tabs_router

# register routers
fastapi_app.include_router(websocket_router)
fastapi_app.include_router(optimization_router)
fastapi_app.include_router(monte_carlo_router)
fastapi_app.include_router(exchange_router)
fastapi_app.include_router(backtest_router)
fastapi_app.include_router(candles_router)
fastapi_app.include_router(strategy_router)
fastapi_app.include_router(auth_router)
fastapi_app.include_router(config_router)
fastapi_app.include_router(notification_router)
fastapi_app.include_router(system_router)
fastapi_app.include_router(file_router)
fastapi_app.include_router(lsp_router)
fastapi_app.include_router(closed_trade_router)
fastapi_app.include_router(order_router)
fastapi_app.include_router(tabs_router)

# # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Live Trade Plugin
# # # # # # # # # # # # # # # # # # # # # # # # # # # #
if jh.has_live_trade_plugin():
    from openquant.controllers.live_controller import router as live_router
    fastapi_app.include_router(live_router)


# # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Static Files (Must be loaded at the end to prevent overlapping with API endpoints)
# # # # # # # # # # # # # # # # # # # # # # # # # # # #
fastapi_app.mount("/", StaticFiles(directory=f"{JESSE_DIR}/static"), name="static")
