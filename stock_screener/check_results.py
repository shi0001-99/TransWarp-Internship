import requests

r = requests.get('http://127.0.0.1:5000/api/results')
data = r.json()

print(f"选股结果: {data['data']['total_results']} 只")
print()

for i, s in enumerate(data['data']['top_stocks']):
    print(f"{i+1}. {s['name']}({s['code']}): {s['total_score']:.1f}分 | {s['grade']}")
    print(f"   建议: {s['advice']}")