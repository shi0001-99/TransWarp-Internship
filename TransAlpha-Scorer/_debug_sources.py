import sys
sys.path.insert(0, "src")

# 1. 宏观数据
print("=== 宏观 ===")
from transalpha.data.data_fetcher import DataFetcher
df = DataFetcher()
macro = df.fetch_macro_data()
for k, v in macro.items():
    print(f"  {k} = {v}")

# 2. 资金流向
print("\n=== 资金流向 ===")
ff = df.fetch_fund_flow_data()
for k, v in ff.items():
    print(f"  {k} = {v}")

# 3. 行业PE/PB分位
print("\n=== 行业分位 ===")
import efinance as ef
raw = ef.stock.get_base_info(["688036"])
row = raw.iloc[0]
pe = row.get("市盈率(动)", "N/A")
pb = row.get("市净率", "N/A")
bk = row.get("板块编号", "N/A")
ind = row.get("所处行业", "N/A")
print(f"  股票PE(绝对) = {pe}")
print(f"  股票PB(绝对) = {pb}")
print(f"  板块编号 = {bk}")
print(f"  所处行业 = {ind}")
print("  get_members结果:")
members = ef.stock.get_members(bk)
print(f"    shape = {members.shape}, empty = {members.empty if hasattr(members, 'empty') else '?'}")
# 尝试通过行业名称搜索
try:
    members2 = ef.stock.get_members(ind.replace(" ", ""))
    print(f"  通过行业名搜索: shape = {members2.shape}, empty = {members2.empty}")
except Exception as e:
    print(f"  通过行业名搜索失败: {e}")
