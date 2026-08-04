"""
Bybit API 通信层
负责请求签名、HTTP 封装、错误处理、速率限制跟踪
"""
import hashlib
import hmac
import json
import time
import urllib.request
import urllib.error
import urllib.parse
import ssl
import socket
from dataclasses import dataclass
from typing import Any, Optional

from ..config.config_manager import AppConfig


@dataclass
class ApiRateLimit:
    """API 速率限制状态"""
    limit: int = 0
    remaining: int = 0
    used: int = 0
    banned: bool = False
    banned_until: float = 0.0  # 解封时间戳
    tier: int = 0  # 限流档位: 0无/2 IP访问超限/3 IP封禁


@dataclass
class VpnStatus:
    """连接状态"""
    connected: bool = False
    latency_ms: int = 0
    level: str = "red"  # green / yellow / red
    label: str = "未测试"


class BybitApiError(Exception):
    """Bybit API 异常"""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class BybitClient:
    """Bybit V5 API 客户端"""

    RECV_WINDOW = 5000
    BYBIT_HOST = "api.bybit.com"

    def __init__(self, config: AppConfig):
        self._config = config
        self._ssl_context = ssl.create_default_context()
        self._setup_opener()
        self._rate_limit = ApiRateLimit()
        self._vpn_status = VpnStatus()

    def _setup_opener(self):
        """安装全局 opener（含代理和 SSL）"""
        handlers = []
        proxy = self._config.proxy
        if proxy.enabled:
            proxies = {}
            if proxy.http:
                proxies["http"] = proxy.http
            if proxy.https:
                proxies["https"] = proxy.https
            if proxies:
                handlers.append(urllib.request.ProxyHandler(proxies))
        handlers.append(urllib.request.HTTPSHandler(context=self._ssl_context))
        opener = urllib.request.build_opener(*handlers)
        urllib.request.install_opener(opener)

    def _sign(self, timestamp: str, param_str: str) -> str:
        """生成 Bybit V5 请求签名"""
        raw = timestamp + self._config.api_key + str(self.RECV_WINDOW) + param_str
        return hmac.new(
            self._config.api_secret.encode("utf-8"),
            raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _update_rate_limit(self, headers: dict):
        """从响应头更新速率限制"""
        try:
            limit = headers.get("X-Bapi-Limit", "")
            status = headers.get("X-Bapi-Limit-Status", "")
            if limit:
                self._rate_limit.limit = int(limit)
            if status:
                self._rate_limit.remaining = int(status)
                self._rate_limit.used = self._rate_limit.limit - self._rate_limit.remaining
        except Exception:
            pass

    @property
    def rate_limit(self) -> ApiRateLimit:
        # 自动解封
        import time as _t
        if self._rate_limit.banned and _t.time() >= self._rate_limit.banned_until:
            self._rate_limit.banned = False
            self._rate_limit.banned_until = 0.0
        return self._rate_limit

    @property
    def vpn_status(self) -> VpnStatus:
        return self._vpn_status

    def test_latency(self) -> VpnStatus:
        """测试到 Bybit 服务器的延迟（走代理）"""
        url = self._config.base_url + "/v5/market/time"
        start = time.time()
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                elapsed = int((time.time() - start) * 1000)
                self._vpn_status.connected = True
                self._vpn_status.latency_ms = elapsed
                if elapsed < 100:
                    self._vpn_status.level = "green"
                elif elapsed < 300:
                    self._vpn_status.level = "yellow"
                else:
                    self._vpn_status.level = "red"
                self._vpn_status.label = f"{elapsed}ms"
        except Exception:
            self._vpn_status.connected = False
            self._vpn_status.latency_ms = 0
            self._vpn_status.level = "red"
            self._vpn_status.label = "断连"
        return self._vpn_status

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        body: Optional[dict] = None,
        use_full_url: bool = False,
    ) -> dict:
        """通用 HTTP 请求"""
        if use_full_url:
            url = endpoint
        else:
            url = self._config.base_url + endpoint
        timestamp = str(int(time.time() * 1000))

        if method == "GET":
            query_string = urllib.parse.urlencode(params or {})
            full_url = f"{url}?{query_string}" if query_string else url
            sign = self._sign(timestamp, query_string)
            data = None
            headers = {
                "X-BAPI-API-KEY": self._config.api_key,
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-SIGN": sign,
                "X-BAPI-RECV-WINDOW": str(self.RECV_WINDOW),
                "Content-Type": "application/json",
            }
        elif method == "POST_FORM":
            query_string = urllib.parse.urlencode(params or {})
            full_url = url
            sign = self._sign(timestamp, query_string)
            data = query_string.encode("utf-8")
            headers = {
                "X-BAPI-API-KEY": self._config.api_key,
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-SIGN": sign,
                "X-BAPI-RECV-WINDOW": str(self.RECV_WINDOW),
                "Content-Type": "application/json",
            }
        else:
            full_url = url
            body_json = json.dumps(body or {})
            sign = self._sign(timestamp, body_json)
            data = body_json.encode("utf-8")
            headers = {
                "X-BAPI-API-KEY": self._config.api_key,
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-SIGN": sign,
                "X-BAPI-RECV-WINDOW": str(self.RECV_WINDOW),
                "Content-Type": "application/json",
            }

        req = urllib.request.Request(full_url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self._update_rate_limit(dict(resp.headers))
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                import time as _t
                self._rate_limit.banned = True
                self._rate_limit.banned_until = _t.time() + 360
                self._rate_limit.tier = 2
                retry_after = e.headers.get("Retry-After", "")
                if retry_after:
                    try:
                        self._rate_limit.banned_until = _t.time() + max(360, int(retry_after))
                    except Exception:
                        pass
                raise BybitApiError(e.code, "请求过于频繁，已触发②档限流(IP访问超限)")
            if e.code == 403:
                import time as _t
                self._rate_limit.banned = True
                self._rate_limit.banned_until = _t.time() + 1800
                self._rate_limit.tier = 3
                raise BybitApiError(e.code, "IP已被封禁，已触发③档限流")
            try:
                body_text = e.read().decode("utf-8")
                result = json.loads(body_text)
            except Exception:
                raise BybitApiError(e.code, f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise BybitApiError(-1, f"网络错误: {e.reason}")
        except Exception as e:
            raise BybitApiError(-1, f"请求异常: {str(e)}")

        if result.get("retCode") != 0:
            raise BybitApiError(
                result.get("retCode", -1),
                result.get("retMsg", "未知错误"),
            )

        return result

    def get(self, endpoint: str, params: Optional[dict] = None, use_full_url: bool = False) -> dict:
        """GET 请求"""
        return self._request("GET", endpoint, params=params, use_full_url=use_full_url)

    def post(self, endpoint: str, body: Optional[dict] = None, use_full_url: bool = False) -> dict:
        """POST 请求"""
        return self._request("POST", endpoint, body=body, use_full_url=use_full_url)

    def post_form(self, endpoint: str, params: dict) -> dict:
        """POST 请求（URL 编码格式，用于闪兑等接口）"""
        return self._request("POST_FORM", endpoint, params=params)

    # ==================== 闪兑 API ====================

    def get_exchange_coins(self, account_type: str = "UNIFIED") -> dict:
        """获取可兑换币种列表"""
        return self.get("/v5/asset/exchange/query-coin-list", {
            "accountType": "eb_convert_uta",
        })

    def get_exchange_quote(self, from_coin: str, to_coin: str, amount: str) -> dict:
        """获取闪兑换报价"""
        return self.post("/v5/asset/exchange/quote-apply", {
            "fromCoin": from_coin,
            "toCoin": to_coin,
            "requestCoin": from_coin,
            "requestAmount": amount,
            "accountType": "eb_convert_uta",
        })

    def submit_exchange(self, quote_tx_id: str) -> dict:
        """提交闪兑换订单"""
        return self.post("/v5/asset/exchange/convert-execute", {
            "quoteTxId": quote_tx_id,
        })
