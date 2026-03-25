from openquant import exceptions
import openquant.helpers as jh
from openquant.services import logger


def validate_routes(router) -> None:
    if not router.routes:
        raise exceptions.RouteNotFound(
            'No routes found. Please add at least one route at: routes.py\nMore info: https://docs.openquant.trade/docs/routes.html#routing')

    # validation for number of routes in the live mode
    if jh.is_live():
        if len(router.routes) > 10:
            logger.broadcast_error_without_logging('Too many routes (not critical, but use at your own risk): Using that more than 5 routes in live/paper trading is not recommended because exchange WS connections are often not reliable for handling that much traffic.')
