"""Drop-in replacement for pytrends that gets Google Trends data from a hosted API, so it doesn't hit 429 errors.

    from pytrends_cloud.request import TrendReq   # was: from pytrends.request import TrendReq
"""

from .request import TrendReq

__all__ = ["TrendReq"]
__version__ = "0.1.0"
