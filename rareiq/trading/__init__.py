"""Paper-first securities research tools for RareIQ.

The package intentionally has no live-broker mode.  It is isolated from the
trading-card application so research code cannot accidentally affect Studio X.
"""

from rareiq.trading.config import TradingConfig

__all__ = ["TradingConfig"]

