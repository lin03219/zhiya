import sys
sys.path.insert(0, r"D:\L\Documents\BIT质押请求")
from bybit_staking.config.config_manager import ConfigManager
from bybit_staking.api.bybit_client import BybitClient, BybitApiError

cm = ConfigManager()
c = cm.load()
cl = BybitClient(c)

# 仓位
print("=== 持仓 ===")
try:
    r = cl.get("/v5/crypto-loan-flexible/position")
    result = r.get("result", {})
    bl = result.get("borrowList", [])
    clist = result.get("collateralList", [])
    print(f"借款列表: {bl}")
    print(f"抵押品列表: {clist}")
    print(f"总债务: {result.get('totalDebt', '0')}")
    print(f"LTV: {result.get('ltv', '--')}")
except BybitApiError as e:
    print(f"[{e.code}] {e.message[:80]}")

# 未还订单
print("\n=== 未还订单 ===")
try:
    r = cl.get("/v5/crypto-loan-flexible/unpaid-loan-order")
    orders = r.get("result", {}).get("list", [])
    print(f"未还订单数: {len(orders)}")
    for o in orders[:3]:
        print(f"  {o.get('loanCurrency')} {o.get('flexibleTotalDebt', o.get('initialLoanAmount', '?'))} status={o.get('status')}")
except BybitApiError as e:
    print(f"[{e.code}] {e.message[:80]}")
