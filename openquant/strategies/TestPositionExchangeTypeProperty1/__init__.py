from openquant.strategies import Strategy
import openquant.helpers as jh
from openquant import utils


class TestPositionExchangeTypeProperty1(Strategy):
    def before(self) -> None:
        if self.index == 0:
            assert self.exchange_type == 'futures'

    def should_long(self):
        return False

    def go_long(self):
        pass

    def should_cancel_entry(self):
        return False
