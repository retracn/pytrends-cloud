"""pytrends-compatible ``TrendReq`` backed by a hosted Google Trends API.

pytrends calls Google's unofficial endpoints from your own IP, so Google answers busy scripts, servers and
notebooks with 429 Too Many Requests, and the project is archived. This class keeps pytrends' methods and
return types, but each query runs AutomationNation's Google Trends Scraper on Apify, which rotates IPs and
retries for you. Set ``APIFY_TOKEN`` (free account: https://console.apify.com/sign-up) or pass ``apify_token``.

One query (``build_payload``) is fetched once and cached: interest over time, regions and related queries
come from the same run. Billing is per keyword report on your Apify account ($1 per 1,000 at the time of
writing, so a 5-keyword query costs half a cent).
"""

import json
import os
import re
import warnings

import pandas as pd
import requests

from .exceptions import ResponseError

ACTOR = "automationnation~google-trends-scraper"
API = "https://api.apify.com/v2"
TIMEFRAMES = {"now 1-H", "now 4-H", "now 1-d", "now 7-d", "today 1-m", "today 3-m", "today 12-m", "today 5-y", "all"}
GPROPS = {"", "images", "news", "youtube", "froogle"}
RESOLUTIONS = {"COUNTRY": "COUNTRY", "REGION": "REGION", "CITY": "CITY", "DMA": "DMA"}
# pytrends' trending_searches(pn=...) takes country names; Google Trends takes codes.
COUNTRIES = {
    "argentina": "AR", "australia": "AU", "austria": "AT", "belgium": "BE", "brazil": "BR", "canada": "CA",
    "chile": "CL", "colombia": "CO", "czech_republic": "CZ", "czechia": "CZ", "denmark": "DK", "egypt": "EG",
    "finland": "FI", "france": "FR", "germany": "DE", "greece": "GR", "hong_kong": "HK", "hungary": "HU",
    "india": "IN", "indonesia": "ID", "ireland": "IE", "israel": "IL", "italy": "IT", "japan": "JP",
    "kenya": "KE", "malaysia": "MY", "mexico": "MX", "netherlands": "NL", "new_zealand": "NZ", "nigeria": "NG",
    "norway": "NO", "philippines": "PH", "poland": "PL", "portugal": "PT", "romania": "RO", "russia": "RU",
    "saudi_arabia": "SA", "singapore": "SG", "south_africa": "ZA", "south_korea": "KR", "spain": "ES",
    "sweden": "SE", "switzerland": "CH", "taiwan": "TW", "thailand": "TH", "turkey": "TR", "ukraine": "UA",
    "united_arab_emirates": "AE", "united_kingdom": "GB", "united_states": "US", "vietnam": "VN",
}


def _country(pn):
    pn = str(pn).strip()
    return pn.upper() if len(pn) == 2 else COUNTRIES.get(pn.lower().replace(" ", "_"), pn.upper())


class TrendReq:
    """Google Trends client with the pytrends interface. Extra pytrends arguments (proxies, retries…) are accepted and ignored."""

    GET_METHOD = "get"
    POST_METHOD = "post"

    def __init__(self, hl="en-US", tz=360, geo="", timeout=(2, 5), proxies="", retries=0, backoff_factor=0,
                 requests_args=None, apify_token=None, wait_secs=300):
        self.hl = hl
        self.tz = tz
        self.geo = geo
        self.token = apify_token or os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_API_TOKEN")
        self.wait_secs = min(int(wait_secs), 300)
        self.kw_list = []
        self.payload = None
        self._cache = {}

    # -- pytrends API ------------------------------------------------------------------------------------

    def build_payload(self, kw_list, cat=0, timeframe="today 5-y", geo="", gprop=""):
        if isinstance(kw_list, str):
            kw_list = [kw_list]
        if not kw_list or len(kw_list) > 5:
            raise ValueError("Google Trends compares 1 to 5 keywords at a time.")
        if gprop not in GPROPS:
            raise ValueError(f"gprop must be one of {sorted(GPROPS)}.")
        self.kw_list = list(kw_list)
        self.payload = {"cat": cat, "timeframe": timeframe, "geo": geo or self.geo, "gprop": gprop}

    def interest_over_time(self):
        reports = self._reports()
        series, partial = [], {}
        for kw in self.kw_list:
            r = reports.get(kw)
            points = (r or {}).get("timeline") or []
            idx = [_time(p) for p in points]
            series.append(pd.Series([int(p.get("value") or 0) for p in points], index=idx, name=kw, dtype="int64"))
            for t, p in zip(idx, points):
                partial[t] = partial.get(t, False) or bool(p.get("isPartial"))
        if not any(len(s) for s in series):
            return pd.DataFrame()
        df = pd.concat(series, axis=1).fillna(0).astype("int64")
        df.index.name = "date"
        df["isPartial"] = [partial.get(t, False) for t in df.index]
        return df.sort_index()

    def interest_by_region(self, resolution="COUNTRY", inc_low_vol=False, inc_geo_code=False):
        res = RESOLUTIONS.get(str(resolution).upper())
        if not res:
            raise ValueError("resolution must be COUNTRY, REGION, CITY or DMA.")
        reports = self._reports(resolution=res, inc_low_vol=inc_low_vol)
        cols, codes = {}, {}
        for kw in self.kw_list:
            rows = (reports.get(kw) or {}).get("cities" if res == "CITY" else "regions") or []
            cols[kw] = {row["name"]: int(row.get("value") or 0) for row in rows}
            codes.update({row["name"]: row.get("geoCode") for row in rows})
        df = pd.DataFrame(cols).fillna(0).astype("int64")
        df.index.name = "geoName"
        if inc_geo_code:
            df.insert(0, "geoCode", [codes.get(n) for n in df.index])
        return df.sort_index()

    def related_queries(self):
        reports = self._reports()
        out = {}
        for kw in self.kw_list:
            r = reports.get(kw) or {}
            top = pd.DataFrame([{"query": q["query"], "value": int(q.get("value") or 0)} for q in r.get("topQueries") or []], columns=["query", "value"])
            rising = pd.DataFrame([{"query": q["query"], "value": q.get("growthPercent") if q.get("growthPercent") is not None else ("Breakout" if q.get("isBreakout") else None)}
                                   for q in r.get("risingQueries") or []], columns=["query", "value"])
            out[kw] = {"top": top if len(top) else None, "rising": rising if len(rising) else None}
        return out

    def related_topics(self):
        warnings.warn("Google currently withholds related topics from automated requests; returning empty results.", stacklevel=2)
        return {kw: {"top": None, "rising": None} for kw in self.kw_list}

    def trending_searches(self, pn="united_states"):
        items = self._trending(_country(pn), hours=24)
        return pd.DataFrame([t["title"] for t in items])

    def today_searches(self, pn="US"):
        items = self._trending(_country(pn), hours=24)
        return pd.Series([t["title"] for t in items], name="query")

    def realtime_trending_searches(self, pn="US", cat="all", count=300):
        items = self._trending(_country(pn), hours=4, limit=count)
        return pd.DataFrame([{"title": t["title"], "entityNames": t.get("relatedQueries") or []} for t in items], columns=["title", "entityNames"])

    def suggestions(self, keyword):
        warnings.warn("suggestions() isn't supported by pytrends-cloud; returning an empty list.", stacklevel=2)
        return []

    def top_charts(self, date, hl="en-US", tz=300, geo="GLOBAL"):
        raise NotImplementedError("top_charts() isn't supported by pytrends-cloud.")

    # -- internals ---------------------------------------------------------------------------------------

    def _input(self, resolution=None, inc_low_vol=False):
        if not self.payload:
            raise ResponseError("Call build_payload() first.")
        p = self.payload
        tf = str(p["timeframe"]).strip()
        inp = {
            "searchTerms": self.kw_list, "compareAll": len(self.kw_list) > 1, "geo": p["geo"], "searchType": p["gprop"],
            "language": self.hl, "timezoneOffset": int(self.tz), "includeInterestOverTime": True, "includeInterestByRegion": True,
            "includeCities": resolution == "CITY", "includeRelatedQueries": True, "includeRelatedTopics": False,
            "includeLowVolumeRegions": bool(inc_low_vol),
        }
        if resolution:
            inp["regionResolution"] = resolution
        if p["cat"]:
            inp["categoryId"] = int(p["cat"])
        if tf in TIMEFRAMES:
            inp["timeRange"] = tf
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{4}-\d{2}-\d{2}", tf):
            inp["customTimeRange"] = tf
        else:
            raise ValueError(f"Unsupported timeframe {tf!r}: use e.g. 'today 12-m', 'now 7-d' or 'YYYY-MM-DD YYYY-MM-DD'.")
        return inp

    def _reports(self, resolution=None, inc_low_vol=False):
        items = self._run(self._input(resolution, inc_low_vol))
        reports = {}
        for r in items:
            if r.get("type") == "keyword-report":
                reports[r.get("searchTerm")] = r
        # Match each requested keyword even if the service normalised its case or spacing.
        lower = {str(k).strip().lower(): v for k, v in reports.items()}
        return {kw: reports.get(kw) or lower.get(kw.strip().lower()) for kw in self.kw_list}

    def _trending(self, geo, hours=24, limit=0):
        inp = {"trendingGeos": [geo], "trendingHours": hours, "trendingMaxItems": int(limit or 0), "includeNews": False, "language": self.hl}
        return [r for r in self._run(inp) if r.get("type") == "trending-search"]

    def _run(self, inp):
        key = json.dumps(inp, sort_keys=True)
        if key not in self._cache:
            self._cache[key] = self._fetch(inp)
        return self._cache[key]

    def _fetch(self, inp):
        if not self.token:
            raise ResponseError("No Apify API token: set APIFY_TOKEN or pass TrendReq(apify_token=...). "
                                "Free account: https://console.apify.com/sign-up, token: https://console.apify.com/settings/integrations")
        res = requests.post(f"{API}/acts/{ACTOR}/run-sync-get-dataset-items", params={"timeout": self.wait_secs, "clean": "true"},
                            json=inp, headers={"Authorization": f"Bearer {self.token}", "User-Agent": "pytrends-cloud"}, timeout=self.wait_secs + 30)
        if res.status_code == 401:
            raise ResponseError("Apify rejected the API token (check APIFY_TOKEN).", res)
        if res.status_code == 402:
            raise ResponseError("Your Apify account has no credit left for this run: https://console.apify.com/billing", res)
        if res.status_code >= 400:
            try:
                msg = res.json().get("error", {}).get("message")
            except ValueError:
                msg = res.text[:200]
            raise ResponseError(f"The request failed: HTTP {res.status_code}: {msg}", res)
        data = res.json()
        return data if isinstance(data, list) else []


def _time(point):
    """Daily points become dates; hourly points keep their time (UTC, timezone-naive like pytrends)."""
    ts = point.get("timestamp") or point.get("date")
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return t
