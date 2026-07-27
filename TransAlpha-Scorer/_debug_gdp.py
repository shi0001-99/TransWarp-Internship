import sys, socket
socket.setdefaulttimeout(8)
sys.path.insert(0, "src")

import akshare as ak
df = ak.macro_china_gdp()
print("GDP shape:", df.shape)
print("GDP columns:", df.columns.tolist())
if not df.empty:
    print("Last row:")
    print(df.iloc[-1].to_dict())
