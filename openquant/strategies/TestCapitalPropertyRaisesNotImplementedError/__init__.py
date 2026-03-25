from openquant.strategies import Strategy
import openquant.helpers as jh
from openquant import utils


class TestCapitalPropertyRaisesNotImplementedError(Strategy):
    def should_long(self) -> bool:
        self.capital
        return False

    def go_long(self) -> None:
        pass

    def should_cancel_entry(self):
        return False
