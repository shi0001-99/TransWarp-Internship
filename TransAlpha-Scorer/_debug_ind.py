import requests, sys
_orig = requests.Session.request
def _patch(self, m, u, **kw):
    kw["timeout"] = 8
    return _orig(self, m, u, **kw)
requests.Session.request = _patch

sys.path.insert(0, "src")
from transalpha.data.data_fetcher import DataFetcher
df = DataFetcher()
data = df.get_stock_score_data("688036.SH")
ind = data["industry"]
pe_pct = ind.get("pe_percentile")
pb_pct = ind.get("pb_percentile")
print("PE percentile:", pe_pct)
print("PB percentile:", pb_pct)
print("PE list count:", len(ind.get("pe_percentiles", [])))
print("PB list count:", len(ind.get("pb_percentiles", [])))
