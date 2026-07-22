"""
自动保护模块
当 LTV 超过阈值时，自动从统一账户划转 USDT 到资金账户并追加抵押
"""
import decimal
import traceback
from typing import Optional

from ..api.bybit_client import BybitClient, BybitApiError
from ..config.config_manager import ProtectConfig
from ..notify.notifier import Notifier


class ProtectService:
    """自动保护服务"""

    def __init__(self, client: BybitClient, config: ProtectConfig, notifier: Notifier, log_func=None):
        self._client = client
        self._config = config
        self._notifier = notifier
        self._protect_running = False  # 防重入锁
        self._log = log_func or (lambda msg: print(msg))

    def checkAndProtect(self, current_ltv_str: str) -> Optional[str]:
        """检查 LTV 并在需要时执行保护操作，返回操作结果描述（None 表示无需操作）"""
        if not self._config.enabled:
            return None

        # 防重入：上一轮保护未完成则跳过
        if self._protect_running:
            return None  # 上一轮保护未完成

        try:
            ltv_val = float(current_ltv_str.replace("%", ""))
        except (ValueError, TypeError):
            return None

        if ltv_val <= self._config.trigger_ltv:
            return None  # LTV 未超标

        # LTV 超过阈值，加锁开始保护流程
        self._protect_running = True
        self._log(f"[保护] 触发: LTV={current_ltv_str} > {self._config.trigger_ltv}%")

        per_amount = self._config.per_transfer_amount
        min_balance = self._config.min_unified_balance

        # 1. 查统一账户 USDT 余额
        try:
            unified_usdt = self._get_unified_usdt_balance()
        except BybitApiError as e:
            self._protect_running = False
            self._log(f"[保护] 查询余额失败: {e}")
            self._notifier.send_protect_fail(
                f"查询统一账户余额失败: {e.message}", current_ltv_str)
            return f"查询余额失败: {e.message}"

        # 2. 数值检查
        try:
            unified_float = float(unified_usdt)
            min_float = float(min_balance)
            per_float = float(per_amount)
        except (ValueError, TypeError):
            self._protect_running = False
            self._log("[保护] 数值解析异常")
            self._notifier.send_protect_fail("数值解析异常", current_ltv_str)
            return "数值解析异常"

        self._log(f"[保护] 统一USDT={unified_usdt}, 最低={min_balance}, 单笔={per_amount}")
        if unified_float < min_float:
            self._protect_running = False
            self._notifier.send_protect_fail(
                f"统一账户 USDT 余额 ({unified_float:.2f}) 低于最低余额 ({min_float:.2f})，停止划转",
                current_ltv_str)
            return f"统一账户余额不足 ({unified_float:.2f} < {min_float:.2f})"

        # 3. 划转金额
        actual_transfer = min(per_float, unified_float)
        transfer_str = self._format_amount(actual_transfer)

        # 4. 划转（统一账户 → 资金账户）
        try:
            tid = self._transfer_usdt(transfer_str)
            self._log(f"[保护] 划转成功: {transfer_str} USDT, transferId={tid}")
        except BybitApiError as e:
            self._protect_running = False
            self._notifier.send_protect_fail(
                f"划转失败 [{e.code}]: {e.message}", current_ltv_str)
            return f"划转失败: {e.message}"
        except Exception as e:
            self._protect_running = False
            traceback.print_exc()
            self._notifier.send_protect_fail(f"划转异常: {e}", current_ltv_str)
            return f"划转异常: {e}"

        # 5. 追加抵押
        try:
            adjust_id = self._adjust_collateral_add(transfer_str)
            self._log(f"[保护] 追加抵押成功: adjustId={adjust_id}")
        except BybitApiError as e:
            self._protect_running = False
            self._notifier.send_protect_fail(
                f"追加抵押失败 [{e.code}]: {e.message}", current_ltv_str)
            return f"追加抵押失败: {e.message}"
        except Exception as e:
            self._protect_running = False
            traceback.print_exc()
            self._notifier.send_protect_fail(f"追加抵押异常: {e}", current_ltv_str)
            return f"追加抵押异常: {e}"

        # 6. 成功通知，释放锁
        self._log(f"[保护] 即将发送成功通知: amount={transfer_str}, LTV={current_ltv_str}")
        self._protect_running = False
        try:
            self._notifier.send_protect_success(transfer_str, current_ltv_str)
            self._log("[保护] 飞书成功通知已发送")
        except Exception as e_notify:
            self._log(f"[保护] 飞书成功通知发送失败: {e_notify}")
        self._log(f"[保护] 完成: 划转+追加 {transfer_str} USDT, adjustId={adjust_id}")
        return f"成功追加 {transfer_str} USDT (adjustId={adjust_id})"

    def _get_unified_usdt_balance(self) -> str:
        result = self._client.get("/v5/account/wallet-balance", {
            "accountType": "UNIFIED", "coin": "USDT"})
        for item in result.get("result", {}).get("list", []):
            for coin_data in item.get("coin", []):
                if coin_data.get("coin") == "USDT":
                    return coin_data.get("walletBalance", "0")
        return "0"

    def _transfer_usdt(self, amount: str) -> str:
        import uuid
        body = {
            "transferId": str(uuid.uuid4()),
            "coin": "USDT",
            "amount": amount,
            "fromAccountType": "UNIFIED",
            "toAccountType": "FUND",
        }
        result = self._client.post("/v5/asset/transfer/inter-transfer", body=body)
        return str(result.get("result", {}).get("transferId", ""))

    def _adjust_collateral_add(self, amount: str) -> str:
        body = {
            "currency": "USDT",
            "amount": amount,
            "direction": "0",
        }
        result = self._client.post("/v5/crypto-loan-common/adjust-ltv", body=body)
        return str(result.get("result", {}).get("adjustId", ""))

    @staticmethod
    def _format_amount(value: float) -> str:
        d = decimal.Decimal(str(value))
        return str(d.quantize(decimal.Decimal('0.01'), rounding=decimal.ROUND_DOWN))
