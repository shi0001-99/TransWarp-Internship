import sys
sys.path.insert(0, '.')
from screener import StockScreener

screener = StockScreener()
results = screener.run_screening(top_n=10, min_score=30.0)

print(f"\n最终结果: {len(results)} 只")
for i, r in enumerate(results[:5]):
    print(f"{i+1}. {r['name']}({r['code']}): {r['total_score']:.1f}分")
    print(f"   均线排列: {r['ma_alignment']['alignment']}")
    print(f"   价格位置: {r['price_position']}%")
    print(f"   换手率: {r['turnover_rate']}%")