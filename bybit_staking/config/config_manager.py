"""
配置管理模块
负责 API 密钥、代理设置、网络切换的持久化存储
"""
import json
import base64
import os
from dataclasses import dataclass, field, asdict
from typing import Optional


# 默认配置目录
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".bybit_staking")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


@dataclass
class ProxyConfig:
    """代理配置"""
    enabled: bool = False
    http: str = ""
    https: str = ""


@dataclass
class NotifyConfig:
    """通知配置"""
    feishu_webhook: str = ""
    dingtalk_webhook: str = ""


@dataclass
class AppConfig:
    """应用总配置"""
    api_key: str = ""
    api_secret: str = ""
    network: str = "mainnet"           # mainnet / testnet
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    borrow_rate: float = 2.5           # 借币请求间隔（秒）
    update_url: str = ""               # 版本检查 URL（JSON 含 version 字段）

    BYBIT_MAINNET = "https://api.bybit.com"
    BYBIT_TESTNET = "https://api-testnet.bybit.com"

    @property
    def base_url(self) -> str:
        """根据 network 返回对应的基础 URL"""
        return self.BYBIT_TESTNET if self.network == "testnet" else self.BYBIT_MAINNET


class ConfigManager:
    """配置管理器：读写加密存储"""

    def __init__(self, config_path: str = CONFIG_FILE):
        self._config_path = config_path
        self._config = AppConfig()
        self._ensure_dir()

    def _ensure_dir(self):
        """确保配置目录存在"""
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)

    @staticmethod
    def _obfuscate(text: str) -> str:
        """简单混淆，避免明文存储密钥"""
        if not text:
            return ""
        return base64.b64encode(text.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _deobfuscate(text: str) -> str:
        """解混淆"""
        if not text:
            return ""
        try:
            return base64.b64decode(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def load(self) -> AppConfig:
        """从文件加载配置"""
        if not os.path.exists(self._config_path):
            return self._config
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._config.api_key = self._deobfuscate(data.get("api_key", ""))
            self._config.api_secret = self._deobfuscate(data.get("api_secret", ""))
            self._config.network = data.get("network", "mainnet")
            proxy_data = data.get("proxy", {})
            self._config.proxy = ProxyConfig(
                enabled=proxy_data.get("enabled", False),
                http=proxy_data.get("http", ""),
                https=proxy_data.get("https", ""),
            )
            notify_data = data.get("notify", {})
            self._config.notify = NotifyConfig(
                feishu_webhook=notify_data.get("feishu_webhook", ""),
                dingtalk_webhook=notify_data.get("dingtalk_webhook", ""),
            )
            self._config.borrow_rate = float(data.get("borrow_rate", 2.5))
            self._config.update_url = data.get("update_url", "")
        except Exception:
            pass
        return self._config

    def save(self) -> None:
        """保存配置到文件"""
        data = {
            "api_key": self._obfuscate(self._config.api_key),
            "api_secret": self._obfuscate(self._config.api_secret),
            "network": self._config.network,
            "proxy": asdict(self._config.proxy),
            "notify": asdict(self._config.notify),
            "borrow_rate": self._config.borrow_rate,
            "update_url": self._config.update_url,
        }
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_config(self) -> AppConfig:
        """获取当前配置"""
        return self._config

    def set_api_credentials(self, api_key: str, api_secret: str) -> None:
        """设置 API 密钥"""
        self._config.api_key = api_key
        self._config.api_secret = api_secret

    def set_network(self, network: str) -> None:
        """切换网络：mainnet / testnet"""
        if network not in ("mainnet", "testnet"):
            raise ValueError(f"无效的网络类型: {network}，仅支持 mainnet / testnet")
        self._config.network = network

    def set_proxy(self, http: str = "", https: str = "", enabled: bool = True) -> None:
        """设置代理"""
        self._config.proxy = ProxyConfig(enabled=enabled, http=http, https=https)

    def set_notify(self, feishu_webhook: str = "", dingtalk_webhook: str = "") -> None:
        """设置通知 Webhook"""
        self._config.notify = NotifyConfig(
            feishu_webhook=feishu_webhook,
            dingtalk_webhook=dingtalk_webhook,
        )

    def set_borrow_rate(self, rate: float) -> None:
        """设置借币请求速率（秒）"""
        self._config.borrow_rate = rate

    def set_update_url(self, url: str) -> None:
        """设置版本检查 URL"""
        self._config.update_url = url
