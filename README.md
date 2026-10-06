# pytrends-cloud: a drop-in pytrends replacement without 429 errors

[pytrends](https://github.com/GeneralMills/pytrends) is archived, and Google answers it with `TooManyRequestsError: The request failed: Google returned a response with code 429`, especially from servers, Colab and CI. **pytrends-cloud keeps the pytrends interface, so your code doesn't change**. The data comes from a hosted Google Trends API that rotates IPs and retries for you.

```diff
- from pytrends.request import TrendReq
+ from pytrends_cloud.request import TrendReq
```

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/retracn/pytrends-cloud/blob/main/examples/google_trends_in_colab.ipynb) Try it in a Colab notebook, where the original library is usually blocked.

## Install

```bash
pip install git+https://github.com/retracn/pytrends-cloud
```

You need an Apify API token: create a [free Apify account](https://console.apify.com/sign-up), copy the token from [Settings → API & Integrations](https://console.apify.com/settings/integrations) and set `APIFY_TOKEN`, or pass `TrendReq(apify_token="...")`.

## Use it exactly like pytrends

```python
from pytrends_cloud.request import TrendReq

pytrends = TrendReq(hl="en-US", tz=360)
pytrends.build_payload(["chatgpt", "claude"], timeframe="today 3-m", geo="US")

pytrends.interest_over_time()          # DataFrame: date index, one column per keyword, isPartial
pytrends.interest_by_region()          # DataFrame indexed by geoName (COUNTRY, REGION, CITY or DMA)
pytrends.related_queries()             # {"chatgpt": {"top": DataFrame, "rising": DataFrame}, ...}
pytrends.trending_searches(pn="united_kingdom")
```

| pytrends method | pytrends-cloud |
|---|---|
| `build_payload(kw_list, cat, timeframe, geo, gprop)` | Same arguments: up to 5 keywords; timeframes like `today 12-m`, `now 7-d` or `YYYY-MM-DD YYYY-MM-DD`; `gprop` is images, news, youtube or froogle |
| `interest_over_time()` | Same DataFrame, terms on one 0–100 scale |
| `interest_by_region(resolution, inc_low_vol, inc_geo_code)` | Same |
| `related_queries()` | Same; rising values are growth percentages, or "Breakout" |
| `trending_searches(pn)`, `today_searches(pn)`, `realtime_trending_searches(pn)` | Same |
| `related_topics()` | Returns empty results: Google currently withholds related topics from automated requests |
| `suggestions()`, `top_charts()` | Not supported |

Arguments pytrends uses for its own HTTP handling (`proxies`, `retries`, `backoff_factor`, `timeout`) are accepted and ignored.

## Cost

Each `build_payload` query runs once and is cached, so interest over time, regions and related queries for the same query come from one run. It runs [Google Trends Scraper](https://apify.com/automationnation/google-trends-scraper) on your Apify account at $1 per 1,000 keyword reports: a 5-keyword query costs half a cent, and Apify's free monthly credit covers about 5,000 reports.

## How it works

`TrendReq` sends your query to the Apify API (`run-sync-get-dataset-items`) and turns the result into the same pandas objects pytrends returns. Your token is only sent to `api.apify.com`.

More: [pytrends alternatives and the 429 error, explained](https://retracn.github.io/automationnation-actors/guides/pytrends-alternative/) · [Google Trends scrapers compared](https://retracn.github.io/automationnation-actors/compare/google-trends-scrapers/)

Not affiliated with Google or the pytrends authors. MIT licensed.
