from .GateSpotMain import GateSpotMain
from openquant.enums import exchanges


class GateSpot(GateSpotMain):
    def __init__(self) -> None:
        super().__init__(
            name=exchanges.GATE_SPOT,
            rest_endpoint='https://api.gateio.ws/api/v4/spot'
        )
