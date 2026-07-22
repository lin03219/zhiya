"""
通知推送模块
支持质押成功后通过飞书/钉钉 Webhook 发送通知
"""
import json
import time
import urllib.request
import urllib.error
from typing import Optional

from ..config.config_manager import NotifyConfig


class Notifier:
    """通知推送器"""

    def __init__(self, config: NotifyConfig):
        self._config = config

    def _post_json(self, url: str, payload: dict) -> tuple[bool, str]:
        """发送 JSON POST 请求，返回 (成功, 错误信息)"""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                # 飞书返回 code=0 表示成功
                code = result.get("code", result.get("errcode", 0))
                if code == 0:
                    return (True, "")
                return (False, f"返回错误: {body[:200]}")
        except urllib.error.HTTPError as e:
            return (False, f"HTTP {e.code}: {e.reason}")
        except Exception as e:
            return (False, str(e))

    def send(
        self,
        title: str,
        content: str,
        platform: str = "all",
    ) -> dict[str, bool]:
        """发送通知，返回每平台成功/失败"""
        results = {}

        if platform in ("feishu", "all") and self._config.feishu_webhook:
            ok, err = self._send_feishu(title, content)
            results["feishu"] = ok
            if err:
                results["feishu_err"] = err

        if platform in ("dingtalk", "all") and self._config.dingtalk_webhook:
            ok, err = self._send_dingtalk(title, content)
            results["dingtalk"] = ok
            if err:
                results["dingtalk_err"] = err

        return results

    def _send_feishu(self, title: str, content: str) -> tuple[bool, str]:
        """飞书富文本消息"""
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "green",
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": content,
                    }
                ],
            },
        }
        return self._post_json(self._config.feishu_webhook, payload)

    def _send_dingtalk(self, title: str, content: str) -> tuple[bool, str]:
        """钉钉 Markdown 消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"## {title}\n\n{content}",
            },
        }
        return self._post_json(self._config.dingtalk_webhook, payload)

    def send_stake_success(
        self,
        order_id: str,
        collateral_coin: str,
        collateral_amount: str,
        loan_coin: str,
        loan_amount: str,
    ) -> dict[str, bool]:
        """质押成功通知"""
        title = "\u2705 质押借币成功"
        content = (
            f"**订单号**: {order_id}\n"
            f"**质押币种**: {collateral_coin}\n"
            f"**质押数量**: {collateral_amount}\n"
            f"**借入币种**: {loan_coin}\n"
            f"**借入数量**: {loan_amount}\n"
            f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.send(title, content, platform="all")

    def send_protect_success(
        self,
        transfer_amount: str,
        current_ltv: str,
    ) -> dict[str, bool]:
        """保护追加抵押成功通知"""
        title = "\U0001f6e1 保护追加抵押成功"
        content = (
            f"**操作**: 自动追加抵押\n"
            f"**划转金额**: {str(transfer_amount)} USDT\n"
            f"**当前 LTV**: {str(current_ltv)}\n"
            f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.send(title, content, platform="feishu")

    def send_protect_fail(
        self,
        reason: str,
        current_ltv: str,
    ) -> dict[str, bool]:
        """保护追加抵押失败告警"""
        title = "\u26a0\ufe0f 保护追加抵押失败"
        content = (
            f"**失败原因**: {str(reason)}\n"
            f"**当前 LTV**: {str(current_ltv)}\n"
            f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"\u2757 请及时检查账户余额，手动追加抵押"
        )
        return self.send(title, content, platform="feishu")
