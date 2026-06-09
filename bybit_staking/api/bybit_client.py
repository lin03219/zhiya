"""
Bybit API 閫氫俊灞?
璐熻矗璇锋眰绛惧悕銆丠TTP 灏佽銆侀敊璇鐞嗐€侀€熺巼闄愬埗璺熻釜
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

from config.config_manager import AppConfig


@dataclass
class ApiRateLimit:
    """API 閫熺巼闄愬埗鐘舵€?""
    limit: int = 0
    remaining: int = 0
    used: int = 0
    banned: bool = False
    banned_until: float = 0.0  # 瑙ｅ皝鏃堕棿鎴?


@dataclass
class VpnStatus:
    """杩炴帴鐘舵€?""
    connected: bool = False
    latency_ms: int = 0
    level: str = "red"  # green / yellow / red
    label: str = "鏈祴璇?


class BybitApiError(Exception):
    """Bybit API 寮傚父"""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class BybitClient:
    """Bybit V5 API 瀹㈡埛绔?""

    RECV_WINDOW = 5000
    BYBIT_HOST = "api.bybit.com"

    def __init__(self, config: AppConfig):
        self._config = config
        self._ssl_context = ssl.create_default_context()
        self._setup_opener()
        self._rate_limit = ApiRateLimit()
        self._vpn_status = VpnStatus()

    def _setup_opener(self):
        """瀹夎鍏ㄥ眬 opener锛堝惈浠ｇ悊鍜?SSL锛?""
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
        """鐢熸垚 Bybit V5 璇锋眰绛惧悕"""
        raw = timestamp + self._config.api_key + str(self.RECV_WINDOW) + param_str
        return hmac.new(
            self._config.api_secret.encode("utf-8"),
            raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _update_rate_limit(self, headers: dict):
        """浠庡搷搴斿ご鏇存柊閫熺巼闄愬埗"""
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
        # 鑷姩瑙ｅ皝
        import time as _t
        if self._rate_limit.banned and _t.time() >= self._rate_limit.banned_until:
            self._rate_limit.banned = False
            self._rate_limit.banned_until = 0.0
        return self._rate_limit

    @property
    def vpn_status(self) -> VpnStatus:
        return self._vpn_status

    def test_latency(self) -> VpnStatus:
        """娴嬭瘯鍒?Bybit 鏈嶅姟鍣ㄧ殑寤惰繜锛堣蛋浠ｇ悊锛?""
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
            self._vpn_status.label = "鏂繛"
        return self._vpn_status

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        body: Optional[dict] = None,
        use_full_url: bool = False,
    ) -> dict:
        """閫氱敤 HTTP 璇锋眰"""
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
                self._rate_limit.banned_until = _t.time() + 300
                retry_after = e.headers.get("Retry-After", "")
                if retry_after:
                    try:
                        self._rate_limit.banned_until = _t.time() + int(retry_after)
                    except Exception:
                        pass
                raise BybitApiError(e.code, "璇锋眰杩囦簬棰戠箒锛屽凡琚檺娴佸皝绂?)
            try:
                body_text = e.read().decode("utf-8")
                result = json.loads(body_text)
            except Exception:
                raise BybitApiError(e.code, f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise BybitApiError(-1, f"缃戠粶閿欒: {e.reason}")
        except Exception as e:
            raise BybitApiError(-1, f"璇锋眰寮傚父: {str(e)}")

        if result.get("retCode") != 0:
            raise BybitApiError(
                result.get("retCode", -1),
                result.get("retMsg", "鏈煡閿欒"),
            )

        return result

    def get(self, endpoint: str, params: Optional[dict] = None, use_full_url: bool = False) -> dict:
        """GET 璇锋眰"""
        return self._request("GET", endpoint, params=params, use_full_url=use_full_url)

    def post(self, endpoint: str, body: Optional[dict] = None, use_full_url: bool = False) -> dict:
        """POST 璇锋眰"""
        return self._request("POST", endpoint, body=body, use_full_url=use_full_url)
