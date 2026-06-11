"""
闪兑业务层
负责余额查询、汇率询价、闪兑下单
"""
from dataclasses import dataclass
from typing import Optional

from ..api.bybit_client import BybitClient, BybitApiError


@dataclass
class ExchangeableCoin:
    """可兑换币种信息"""
    coin: str = ""
    amount: str = "0"          # 持有数量
    usd_value: str = "0"       # 持有币的USDT估值
    quote_amount: str = ""     # 可兑换USDT金额(询价结果)
    quote_tx_id: str = ""      # 询价交易ID
    quotable: bool = False     # 是否已成功询价
    error_msg: str = ""        # 询价失败原因


class ExchangeService:
    """闪兑业务服务"""

    def __init__(self, client: BybitClient):
        self._client = client

    def getExchangeableBalances(self) -> list[ExchangeableCoin]:
        """获取统一账户中可兑换的非USDT币种列表"""
        result = self._client.get("/v5/account/wallet-balance", {
            "accountType": "UNIFIED",
        })
        coins = []
        for item in result.get("result", {}).get("list", []):
            for coin_info in item.get("coin", []):
                coin = coin_info.get("coin", "")
                wallet_balance = coin_info.get("walletBalance", "0")
                usd_value = coin_info.get("usdValue", "0")
                # 过滤 USDT 和零余额
                if coin == "USDT":
                    continue
                if float(wallet_balance or "0") <= 0:
                    continue
                coins.append(ExchangeableCoin(
                    coin=coin,
                    amount=wallet_balance,
                    usd_value=usd_value,
                ))
        return coins

    def getQuote(self, coin: str, amount: str) -> ExchangeableCoin:
        """对指定币种询价(全额兑USDT)，返回更新后的 ExchangeableCoin"""
        ec = ExchangeableCoin(coin=coin, amount=amount)
        try:
            resp = self._client.get_exchange_quote(coin, "USDT", amount)
            data = resp.get("result", {})
            ec.quote_amount = data.get("toAmount", "")
            ec.quote_tx_id = data.get("quoteTxId", "")
            ec.quotable = bool(ec.quote_tx_id)
        except BybitApiError as e:
            ec.quotable = False
            ec.error_msg = f"{e.message}"
        return ec

    def executeExchange(self, quote_tx_id: str) -> dict:
        """执行闪兑"""
        return self._client.submit_exchange(quote_tx_id)
