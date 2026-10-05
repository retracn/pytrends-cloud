import json
from pathlib import Path

import pandas as pd
import pytest

from pytrends_cloud.exceptions import ResponseError
from pytrends_cloud.request import TrendReq

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def trends(monkeypatch):
    calls = []

    def fake_fetch(self, inp):
        calls.append(inp)
        name = "trending.json" if "trendingGeos" in inp else "keyword-reports.json"
        return json.loads((FIX / name).read_text())

    monkeypatch.setattr(TrendReq, "_fetch", fake_fetch)
    t = TrendReq(hl="en-US", tz=360, apify_token="test")
    t.calls = calls
    return t


def test_input_matches_pytrends_arguments(trends):
    trends.build_payload(["chatgpt", "claude"], cat=0, timeframe="today 3-m", geo="", gprop="youtube")
    trends.interest_over_time()
    inp = trends.calls[0]
    assert inp["searchTerms"] == ["chatgpt", "claude"]
    assert inp["compareAll"] is True
    assert inp["timeRange"] == "today 3-m"
    assert inp["searchType"] == "youtube"
    assert inp["timezoneOffset"] == 360
    trends.build_payload(["coffee"], timeframe="2024-01-01 2024-12-31")
    assert trends._input()["customTimeRange"] == "2024-01-01 2024-12-31"
    with pytest.raises(ValueError):
        trends.build_payload(["a", "b", "c", "d", "e", "f"])


def test_interest_over_time_shape(trends):
    trends.build_payload(["chatgpt", "claude"], timeframe="today 3-m")
    df = trends.interest_over_time()
    assert list(df.columns) == ["chatgpt", "claude", "isPartial"]
    assert df.index.name == "date"
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df["chatgpt"].dtype == "int64" and df["chatgpt"].max() == 100
    assert df["isPartial"].dtype == bool


def test_one_run_per_query(trends):
    trends.build_payload(["chatgpt", "claude"], timeframe="today 3-m")
    trends.interest_over_time()
    trends.related_queries()
    trends.interest_by_region()
    assert len(trends.calls) == 2, "regions with an explicit resolution are a second run; the rest come from the cache"
    trends.interest_by_region()
    assert len(trends.calls) == 2


def test_interest_by_region_and_related_queries(trends):
    trends.build_payload(["chatgpt", "claude"], timeframe="today 3-m")
    reg = trends.interest_by_region(inc_geo_code=True)
    assert reg.index.name == "geoName"
    assert list(reg.columns) == ["geoCode", "chatgpt", "claude"]
    assert reg.loc["China", "geoCode"] == "CN"
    rq = trends.related_queries()
    assert set(rq) == {"chatgpt", "claude"}
    assert list(rq["chatgpt"]["top"].columns) == ["query", "value"]
    assert rq["chatgpt"]["rising"]["value"].iloc[0] == 4250


def test_trending_searches(trends):
    df = trends.trending_searches(pn="united_states")
    assert trends.calls[-1]["trendingGeos"] == ["US"]
    assert df.iloc[0, 0] == "lions vs panthers"
    rt = trends.realtime_trending_searches(pn="US")
    assert list(rt.columns) == ["title", "entityNames"]


def test_missing_token_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    t = TrendReq()
    t.build_payload(["coffee"])
    with pytest.raises(ResponseError, match="APIFY_TOKEN"):
        t.interest_over_time()
