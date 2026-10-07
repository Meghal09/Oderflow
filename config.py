import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    api_key: str = os.getenv("BYBIT_API_KEY", "")
    api_secret: str = os.getenv("BYBIT_API_SECRET", "")
    testnet: bool = os.getenv("BYBIT_TESTNET", "0") == "1"
    symbol: str = os.getenv("SYMBOL", "BTCUSDT")
    tf: str = os.getenv("TIMEFRAME", "1")            # minutes: 1,3,5,15,30,60
    bucket_bps: float = float(os.getenv("FP_BUCKET_BPS", "1.0"))  # footprint price bucket ~ bps of price
    fp_candles: int = 14          # candles drawn in footprint
    roll_candles: int = 30        # rolling CVD window
    imb_ratio: float = 3.0        # diagonal imbalance ratio
    stack_n: int = 3              # stacked imbalance levels = cluster
    wall_mult: float = 4.0        # wall = size >= mult * median book size
    trend_chg: float = 5.0        # REGIME: 24h change % (AlgoDesk TREND trigger)
    vol_ratio: float = 1.5        # REGIME: ATR14/ATR100 => volatile
    funding_thr: float = 0.0015   # FUND/SENT agent threshold (AlgoDesk skill)
    min_rr: float = 1.0

    @property
    def rest_url(self):
        return "https://api-testnet.bybit.com" if self.testnet else "https://api.bybit.com"

    @property
    def ws_url(self):
        return ("wss://stream-testnet.bybit.com/v5/public/linear" if self.testnet
                else "wss://stream.bybit.com/v5/public/linear")


cfg = Config()
