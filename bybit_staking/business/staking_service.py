"""
质押借币业务模块
支持质押、借币、还款、持仓/订单查询、利息查询、余额查询、账内划转
"""
import uuid
from dataclasses import dataclass, field
from typing import Optional

from ..api.bybit_client import BybitClient


@dataclass
class WalletBalance:
    """钱包余额"""
    coin: str = ""
    wallet_balance: str = "0"
    available_balance: str = "0"
    usd_value: str = "0"


@dataclass
class LoanOrder:
    """借贷订单"""
    order_id: str = ""
    collateral_coin: str = ""
    loan_coin: str = ""
    collateral_amount: str = "0"
    loan_amount: str = "0"
    interest_rate: str = "0"
    hourly_interest_rate: str = "0"
    status: str = ""
    created_time: str = ""


@dataclass
class InterestRate:
    """利率信息"""
    coin: str = ""
    hourly_rate: str = "0"
    daily_rate: str = "0"
    yearly_rate: str = "0"


class StakingService:
    """质押借币业务服务"""

    def __init__(self, client: BybitClient):
        self._client = client
        self._pos_cache = {}  # position 缓存
        self._pos_cache_time = 0.0  # 缓存时间戳

    def _fetch_balance(self, account_type: str, coin: Optional[str] = None) -> list[WalletBalance]:
        """通用余额查询"""
        params = {"accountType": account_type}
        if coin:
            params["coin"] = coin
        result = self._client.get("/v5/account/wallet-balance", params=params)
        balances = []
        for item in result.get("result", {}).get("list", []):
            for coin_data in item.get("coin", []):
                balances.append(WalletBalance(
                    coin=coin_data.get("coin", ""),
                    wallet_balance=coin_data.get("walletBalance", "0"),
                    available_balance=coin_data.get("availableToWithdraw", "0"),
                    usd_value=coin_data.get("usdValue", "0"),
                ))
        return balances

    def _sum_usd(self, balances: list[WalletBalance]) -> float:
        """汇总 USD 估值"""
        total = 0.0
        for b in balances:
            try:
                total += float(b.usd_value)
            except (ValueError, TypeError):
                pass
        return total

    def get_unified_balance(self, coin: Optional[str] = None) -> list[WalletBalance]:
        """统一账户余额"""
        return self._fetch_balance("UNIFIED", coin)

    def get_unified_total_usd(self) -> float:
        """统一账户总资产 USD"""
        return self._sum_usd(self.get_unified_balance())

    def get_fund_balance(self, coin: Optional[str] = None) -> list[WalletBalance]:
        """资金账户余额（FUND 用专用接口）"""
        try:
            params = {"accountType": "FUND"}
            result = self._client.get("/v5/asset/transfer/query-account-coins-balance", params=params)
            balances = []
            coins = result.get("result", {}).get("balance", [])
            for item in coins:
                wb = str(item.get("walletBalance", "0"))
                coin_name = item.get("coin", "")
                if coin_name in ("USDT", "USDC", "BUSD", "DAI"):
                    usd_val = wb
                else:
                    usd_val = str(item.get("usdValue", "0"))
                balances.append(WalletBalance(
                    coin=coin_name,
                    wallet_balance=wb,
                    available_balance=str(item.get("transferBalance", "0")),
                    usd_value=usd_val,
                ))
            return balances
        except Exception:
            return []

    def get_fund_total_usd(self) -> float:
        """资金账户总资产 USD"""
        return self._sum_usd(self.get_fund_balance())

    def get_all_total_usd(self) -> float:
        """所有账户总资产 USD"""
        return self.get_unified_total_usd() + self.get_fund_total_usd()

    def calculate_collateral(self, loan_coin: str, loan_amount: str):
        """返回 (所需抵押量, 最大LTV%)"""
        max_ltv = "--"
        try:
            balances = self.get_fund_balance()
            usdt_balance = "0"
            for b in balances:
                if b.coin == "USDT":
                    usdt_balance = b.wallet_balance
                    break
            body = {
                "currency": loan_coin,
                "collateralList": [{"ccy": "USDT", "amount": usdt_balance}],
            }
            result = self._client.post("/v5/crypto-loan-common/max-loan", body=body)
            max_loan = float(result.get("result", {}).get("maxLoan", "0"))
            usdt_bal = float(usdt_balance)
            if max_loan > 0 and usdt_bal > 0:
                ratio = usdt_bal / max_loan
                max_ltv = f"{100 / ratio:.0f}%"
                required = float(loan_amount) * ratio * 1.05
                return (f"{required:.2f}", max_ltv)
        except Exception:
            pass
        try:
            required = float(loan_amount) * 1.2
            return (f"{required:.2f}", max_ltv)
        except Exception:
            return ("0", "--")

    def calculate_max_borrow(self, loan_coin: str) -> dict:
        """根据 LTV ≤ 80% 计算最大可借"""
        result = {
            "can_borrow": False, "max_amount": "0", "max_amount_usd": "0",
            "current_ltv": "--", "projected_ltv": "--", "available_usdt": "0",
            "total_collateral": "0", "total_debt": "0", "coin_borrowable": True,
        }
        try:
            pos = self.get_position()
            total_debt = float(pos.get("totalDebt", "0"))
            total_collateral = float(pos.get("totalCollateral", "0"))
            ltv_raw = pos.get("ltv", "")
            current_ltv = float(ltv_raw) if ltv_raw else 0.0
            result["current_ltv"] = f"{current_ltv * 100:.1f}%"
            result["total_debt"] = str(total_debt)
            result["total_collateral"] = str(total_collateral)

            fund_usdt = 0.0
            # 查资金账户 USDT
            balances = self.get_fund_balance()
            for b in balances:
                if b.coin == "USDT":
                    fund_usdt += float(b.wallet_balance)
                    break
            # 查统一账户 USDT
            try:
                uni_balances = self.get_unified_balance()
                for b in uni_balances:
                    if b.coin == "USDT":
                        fund_usdt += float(b.wallet_balance)
                        break
            except Exception:
                pass
            result["available_usdt"] = str(fund_usdt)

            total_collateral_after = total_collateral + fund_usdt
            if total_collateral_after <= 0:
                return result

            max_debt = total_collateral_after * 0.80
            max_borrow_usd = max_debt - total_debt
            if max_borrow_usd <= 0:
                return result
            result["max_amount_usd"] = f"{max_borrow_usd:.2f}"

            # 先查币种是否可借（用 max-loan 返回判断）
            try:
                trial = self._client.post("/v5/crypto-loan-common/max-loan", body={
                    "currency": loan_coin,
                    "collateralList": [{"ccy": "USDT", "amount": "1"}],
                })
                if not trial.get("result", {}).get("maxLoan", ""):
                    result["coin_borrowable"] = False
                    return result
            except Exception:
                result["coin_borrowable"] = False
                return result

            price = self.get_coin_price(loan_coin)
            if price <= 0:
                return result
            max_amount = max_borrow_usd / price
            result["max_amount"] = f"{max_amount:.4f}"

            projected_ltv = (total_debt + max_borrow_usd) / total_collateral_after
            result["projected_ltv"] = f"{projected_ltv * 100:.1f}%"
            result["can_borrow"] = True
        except Exception:
            pass
        return result

    def get_current_ltv(self) -> str:
        """返回当前持仓 LTV（从 Bybit 直接获取）"""
        try:
            result = self._client.get("/v5/crypto-loan-common/position")
            ltv_raw = result.get("result", {}).get("ltv", "")
            if ltv_raw:
                return f"{float(ltv_raw) * 100:.1f}%"
        except Exception:
            pass
        return "--"

    def get_account_info(self) -> dict:
        """获取账户信息"""
        result = self._client.get("/v5/account/info")
        return result.get("result", {})

    def transfer(
        self,
        coin: str,
        amount: str,
        from_account: str,
        to_account: str,
    ) -> str:
        """账内余额划转"""
        body = {
            "transferId": str(uuid.uuid4()),
            "coin": coin,
            "amount": amount,
            "fromAccountType": from_account,
            "toAccountType": to_account,
        }
        result = self._client.post("/v5/asset/transfer/inter-transfer", body=body)
        return result.get("result", {}).get("transferId", "")

    def borrow(
        self,
        collateral_coin: str,
        loan_coin: str,
        collateral_amount: str,
        loan_amount: str,
    ) -> str:
        """借币（质押借贷）——使用 V5 crypto-loan-flexible 接口"""
        body = {
            "loanCurrency": loan_coin,
            "loanAmount": loan_amount,
            "collateralList": [
                {"currency": collateral_coin, "amount": collateral_amount}
            ],
        }
        result = self._client.post("/v5/crypto-loan-flexible/borrow", body=body)
        data = result.get("result", {})
        return data.get("orderId", "")

    def repay(self, loan_currency: str, amount: str) -> str:
        """还款"""
        body = {"loanCurrency": loan_currency, "amount": amount}
        result = self._client.post("/v5/crypto-loan-flexible/repay", body=body)
        return result.get("result", {}).get("repayId", "")

    def repay_from_collateral(self, loan_currency: str, amount: str) -> str:
        """从抵押品还款（用 USDT 抵押品抵扣，无需账户有该币种）"""
        body = {"loanCurrency": loan_currency, "amount": amount}
        result = self._client.post("/v5/crypto-loan-flexible/repay-collateral", body=body)
        return result.get("result", {}).get("repayId", "")

    def get_coin_price(self, coin: str) -> float:
        """获取币种对 USDT 的当前价格"""
        try:
            result = self._client.get("/v5/market/tickers", params={
                "category": "spot",
                "symbol": f"{coin}USDT",
            })
            items = result.get("result", {}).get("list", [])
            if items:
                return float(items[0].get("lastPrice", "0"))
        except Exception:
            pass
        return 0.0

    def is_coin_borrowable(self, coin: str) -> bool:
        """检查币种是否可借（用 max-loan 接口探测）"""
        try:
            body = {
                "currency": coin,
                "collateralList": [{"ccy": "USDT", "amount": "1"}],
            }
            result = self._client.post("/v5/crypto-loan-common/max-loan", body=body)
            # 有返回且无报错 = 可借
            max_loan = result.get("result", {}).get("maxLoan", "")
            return max_loan != "" and max_loan != "0"
        except Exception:
            return False

    def repay_smart(self, loan_currency: str, debt_amount: str) -> str:
        """智能还款：先尝试用借入币种还款，失败则从抵押品还款（自动转换USDT金额）"""
        import decimal
        try:
            d = decimal.Decimal(str(debt_amount))
            amt = str(d.quantize(decimal.Decimal('0.00000001'), rounding=decimal.ROUND_UP))
        except Exception:
            amt = str(debt_amount)
        try:
            rid = self.repay(loan_currency, amt)
            return rid
        except Exception:
            pass
        price = self.get_coin_price(loan_currency)
        if price <= 0:
            price = 1.0
        try:
            usdt_amt = decimal.Decimal(amt) * decimal.Decimal(str(price))
            usdt_str = str(usdt_amt.quantize(decimal.Decimal('0.01'), rounding=decimal.ROUND_UP))
        except Exception:
            usdt_str = amt
        return self.repay_from_collateral(loan_currency, usdt_str)

    def get_position(self) -> dict:
        """获取当前持仓（2秒缓存）"""
        import time as _t
        now = _t.time()
        if self._pos_cache and (now - self._pos_cache_time) < 2:
            return self._pos_cache
        result = self._client.get("/v5/crypto-loan-common/position")
        data = result.get("result", {})
        self._pos_cache = data
        self._pos_cache_time = now
        return data

    def get_loan_orders(
        self,
        order_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> list[LoanOrder]:
        """查询借贷订单（使用 borrow-history）"""
        params: dict = {"limit": limit}
        result = self._client.get("/v5/crypto-loan-flexible/borrow-history", params=params)
        orders = []
        for item in result.get("result", {}).get("list", []):
            orders.append(LoanOrder(
                order_id=item.get("orderId", ""),
                collateral_coin="",
                loan_coin=item.get("loanCurrency", ""),
                collateral_amount="",
                loan_amount=item.get("initialLoanAmount", "0"),
                interest_rate="",
                hourly_interest_rate="",
                status=str(item.get("status", "")),
                created_time=str(item.get("borrowTime", "")),
            ))
        return orders

    def get_borrow_history(self, limit: int = 20) -> list[dict]:
        """借币历史"""
        result = self._client.get(
            "/v5/crypto-loan-flexible/borrow-history",
            params={"limit": limit},
        )
        return result.get("result", {}).get("list", [])

    def get_repay_history(self, limit: int = 20) -> list[dict]:
        """还款历史"""
        result = self._client.get(
            "/v5/crypto-loan-flexible/repay-orders",
            params={"limit": limit},
        )
        return result.get("result", {}).get("list", [])

    def get_unpaid_orders(self) -> list[dict]:
        """未还订单"""
        result = self._client.get("/v5/crypto-loan-flexible/unpaid-loan-order")
        return result.get("result", {}).get("list", [])

    def get_interest_rate(self, coin: Optional[str] = None) -> list[InterestRate]:
        """查询借贷利率"""
        params = {}
        if coin:
            params["coin"] = coin
        result = self._client.get("/v5/crypto-loan-flexible/interest-rate", params=params)
        rates = []
        for item in result.get("result", {}).get("list", []):
            rates.append(InterestRate(
                coin=item.get("coin", ""),
                hourly_rate=item.get("hourlyRate", "0"),
                daily_rate=item.get("dailyRate", "0"),
                yearly_rate=item.get("yearlyRate", "0"),
            ))
        return rates

    def get_collateral_info(self) -> dict:
        """查询质押品信息"""
        result = self._client.get("/v5/crypto-loan-flexible/collateral-info")
        return result.get("result", {})