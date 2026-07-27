import sys
sys.path.insert(0, "src")

import efinance as ef
raw = ef.stock.get_base_info(["688036"])
print("=== efinance get_base_info columns ===")
print(raw.columns.tolist())
print()
print("=== data ===")
row = raw.iloc[0]
for c in raw.columns:
    print(f"  {c} = {row[c]}")

print()
print("=== 缓存PE/PB ===")
from transalpha.data.data_fetcher import DataFetcher
df = DataFetcher()
info = df.fetch_stock_basic_info("688036.SH")
pe = info.get("_pe")
pb = info.get("_pb")
print(f"_pe = {pe}")
print(f"_pb = {pb}")
print(f"industry_code = {info.get('industry_code')}")
