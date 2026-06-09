"""
璐ㄦ娂鍊熷竵涓氬姟妯″潡
鏀寔璐ㄦ娂銆佸€熷竵銆佽繕娆俱€佹寔浠?璁㈠崟鏌ヨ銆佸埄鎭煡璇€佷綑棰濇煡璇€佽处鍐呭垝杞?
"""
import uuid
from dataclasses import dataclass, field
from typing import Optional

from api.bybit_client import BybitClient


@dataclass
class WalletBalance:
    """閽卞寘浣欓"""
    coin: str = ""
    wallet_balance: str = "0"
    available_balance: str = "0"
    usd_value: str = "0"


@dataclass
class LoanOrder:
    """鍊熻捶璁㈠崟"""
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
    """鍒╃巼淇℃伅"""
    coin: str = ""
    hourly_rate: str = "0"
    daily_rate: str = "0"
    yearly_rate: str = "0"


class StakingService:
    """璐ㄦ娂鍊熷竵涓氬姟鏈嶅姟"""

    def __init__(self, client: BybitClient):
        self._client = client
        self._pos_cache = {}  # position 缂撳瓨
        self._pos_cache_time = 0.0  # 缂撳瓨鏃堕棿鎴?

    def _fetch_balance(self, account_type: str, coin: Optional[str] = None) -> list[WalletBalance]:
        """閫氱敤浣欓鏌ヨ"""
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
        """姹囨€?USD 浼板€?""
        total = 0.0
        for b in balances:
            try:
                total += float(b.usd_value)
            except (ValueError, TypeError):
                pass
        return total

    def get_unified_balance(self, coin: Optional[str] = None) -> list[WalletBalance]:
        """缁熶竴璐︽埛浣欓"""
        return self._fetch_balance("UNIFIED", coin)

    def get_unified_total_usd(self) -> float:
        """缁熶竴璐︽埛鎬昏祫浜?USD"""
        return self._sum_usd(self.get_unified_balance())

    def get_fund_balance(self, coin: Optional[str] = None) -> list[WalletBalance]:
        """璧勯噾璐︽埛浣欓锛團UND 鐢ㄤ笓鐢ㄦ帴鍙ｏ級"""
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
        """璧勯噾璐︽埛鎬昏祫浜?USD"""
        return self._sum_usd(self.get_fund_balance())

    def get_all_total_usd(self) -> float:
        """鎵€鏈夎处鎴锋€昏祫浜?USD"""
        return self.get_unified_total_usd() + self.get_fund_total_usd()

    def calculate_collateral(self, loan_coin: str, loan_amount: str):
        """杩斿洖 (鎵€闇€鎶垫娂閲? 鏈€澶TV%)"""
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
        """鏍规嵁 LTV 鈮?80% 璁＄畻鏈€澶у彲鍊?""
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
            # 鏌ヨ祫閲戣处鎴?USDT
            balances = self.get_fund_balance()
            for b in balances:
                if b.coin == "USDT":
                    fund_usdt += float(b.wallet_balance)
                    break
            # 鏌ョ粺涓€璐︽埛 USDT
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

            # 鍏堟煡甯佺鏄惁鍙€燂紙鐢?max-loan 杩斿洖鍒ゆ柇锛?
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
        """杩斿洖褰撳墠鎸佷粨 LTV锛堜粠 Bybit 鐩存帴鑾峰彇锛?""
        try:
            result = self._client.get("/v5/crypto-loan-common/position")
            ltv_raw = result.get("result", {}).get("ltv", "")
            if ltv_raw:
                return f"{float(ltv_raw) * 100:.1f}%"
        except Exception:
            pass
        return "--"

    def get_account_info(self) -> dict:
        """鑾峰彇璐︽埛淇℃伅"""
        result = self._client.get("/v5/account/info")
        return result.get("result", {})

    def transfer(
        self,
        coin: str,
        amount: str,
        from_account: str,
        to_account: str,
    ) -> str:
        """璐﹀唴浣欓鍒掕浆"""
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
        """鍊熷竵锛堣川鎶煎€熻捶锛夆€斺€斾娇鐢?V5 crypto-loan-flexible 鎺ュ彛"""
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
        """杩樻"""
        body = {"loanCurrency": loan_currency, "amount": amount}
        result = self._client.post("/v5/crypto-loan-flexible/repay", body=body)
        return result.get("result", {}).get("repayId", "")

    def repay_from_collateral(self, loan_currency: str, amount: str) -> str:
        """浠庢姷鎶煎搧杩樻锛堢敤 USDT 鎶垫娂鍝佹姷鎵ｏ紝鏃犻渶璐︽埛鏈夎甯佺锛?""
        body = {"loanCurrency": loan_currency, "amount": amount}
        result = self._client.post("/v5/crypto-loan-flexible/repay-collateral", body=body)
        return result.get("result", {}).get("repayId", "")

    def get_coin_price(self, coin: str) -> float:
        """鑾峰彇甯佺瀵?USDT 鐨勫綋鍓嶄环鏍?""
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
        """妫€鏌ュ竵绉嶆槸鍚﹀彲鍊燂紙鐢?max-loan 鎺ュ彛鎺㈡祴锛?""
        try:
            body = {
                "currency": coin,
                "collateralList": [{"ccy": "USDT", "amount": "1"}],
            }
            result = self._client.post("/v5/crypto-loan-common/max-loan", body=body)
            # 鏈夎繑鍥炰笖鏃犳姤閿?= 鍙€?
            max_loan = result.get("result", {}).get("maxLoan", "")
            return max_loan != "" and max_loan != "0"
        except Exception:
            return False

    def repay_smart(self, loan_currency: str, debt_amount: str) -> str:
        """鏅鸿兘杩樻锛氬厛灏濊瘯鐢ㄥ€熷叆甯佺杩樻锛屽け璐ュ垯浠庢姷鎶煎搧杩樻锛堣嚜鍔ㄨ浆鎹SDT閲戦锛?""
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
        """鑾峰彇褰撳墠鎸佷粨锛?绉掔紦瀛橈級"""
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
        """鏌ヨ鍊熻捶璁㈠崟锛堜娇鐢?borrow-history锛?""
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
        """鍊熷竵鍘嗗彶"""
        result = self._client.get(
            "/v5/crypto-loan-flexible/borrow-history",
            params={"limit": limit},
        )
        return result.get("result", {}).get("list", [])

    def get_repay_history(self, limit: int = 20) -> list[dict]:
        """杩樻鍘嗗彶"""
        result = self._client.get(
            "/v5/crypto-loan-flexible/repay-orders",
            params={"limit": limit},
        )
        return result.get("result", {}).get("list", [])

    def get_unpaid_orders(self) -> list[dict]:
        """鏈繕璁㈠崟"""
        result = self._client.get("/v5/crypto-loan-flexible/unpaid-loan-order")
        return result.get("result", {}).get("list", [])

    def get_interest_rate(self, coin: Optional[str] = None) -> list[InterestRate]:
        """鏌ヨ鍊熻捶鍒╃巼"""
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
        """鏌ヨ璐ㄦ娂鍝佷俊鎭?""
        result = self._client.get("/v5/crypto-loan-flexible/collateral-info")
        return result.get("result", {})