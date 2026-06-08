import sys
file = r"D:\L\Documents\BIT质押请求\bybit_staking\business\staking_service.py"
with open(file, "r", encoding="utf-8") as f:
    content = f.read()

# Find the borrow method and replace it
old = '''    def borrow(
        self,
        collateral_coin: str,
        loan_coin: str,
        collateral_amount: str,
        loan_amount: str,
    ) -> str:
        """借币（质押借贷）"""
        body = {
            "collateralCoin": collateral_coin,
            "loanCoin": loan_coin,
            "collateralAmount": collateral_amount,
            "loanAmount": loan_amount,
            "loanTermType": 1,  # 1=活期, 2=定期
        }
        # 尝试多种可能的接口路径
        endpoints = [
            "/v5/crypto-loan/borrow",
            "/v5/spot-margin-trade/borrow",
            "/v5/unified/borrow",
        ]
        last_error = None
        for ep in endpoints:
            try:
                if ep == "/v5/spot-margin-trade/borrow":
                    # 统一账户保证金借币的参数不同
                    alt_body = {
                        "coin": loan_coin,
                        "qty": loan_amount,
                        "accountType": "UNIFIED",
                    }
                    result = self._client.post(ep, body=alt_body)
                else:
                    result = self._client.post(ep, body=body)
                return result.get("result", {}).get("orderId", "")
            except Exception as e:
                last_error = e
                continue
        raise last_error if last_error else Exception("所有借币接口均失败")'''

new = '''    def borrow(
        self,
        collateral_coin: str,
        loan_coin: str,
        collateral_amount: str,
        loan_amount: str,
    ) -> str:
        """借币（质押借贷）——使用 fixed-loan v1 接口"""
        body = {
            "isLargeBorrow": 0,
            "borrowCoin": loan_coin,
            "borrowQuantity": loan_amount,
            "collateralCoins": [
                {"coin": collateral_coin, "quantity": collateral_amount}
            ],
        }
        result = self._client.post("/x-api/spot/api/fixed-loan/v1/trial-borrow-order", body=body)
        # 接口返回的订单标识可能在 result.data 中
        data = result.get("result", {}) or result.get("data", {})
        return data.get("orderId", data.get("borrowId", ""))'''

content = content.replace(old, new)

with open(file, "w", encoding="utf-8") as f:
    f.write(content)
print("DONE")
