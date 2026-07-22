"""
版本管理模块
"""
import base64

VERSION = "4.0.0"
XOR_KEY = "bybit_staking_xor_key_2026!"

_ENC_UPDATE_URL = "Cg0WGQdlXFsAGwBAADYMBwc9RQYWMh1CV0ZOEVYOABpvQEZQUkYUDzYBDl0tDgkcPkFVQRlNAw0HGgA="
_ENC_RELEASES_URL = "Cg0WGQdlXFsGAh0GEj1WDB0yRAkQMQIDAAcYTQMKAA0+XAYEBwwPFDoL"
_ENC_DOWNLOAD_BASE = "Cg0WGQdlXFsGAh0GEj1WDB0yRAkQMQIDAAcYTQMKAA0+XAYEBwwPFDoLQBYwHAsVMFNU"

def _xor_decode(encoded: str) -> str:
    data = base64.b64decode(encoded)
    key = XOR_KEY.encode()
    return "".join(chr(b ^ key[i % len(key)]) for i, b in enumerate(data))

UPDATE_URL = _xor_decode(_ENC_UPDATE_URL)
RELEASES_URL = _xor_decode(_ENC_RELEASES_URL)
_DOWNLOAD_BASE = _xor_decode(_ENC_DOWNLOAD_BASE)

def get_download_url(tag_name: str) -> str:
    return f"{_DOWNLOAD_BASE}/{tag_name}/BybitStaking.exe"

CHANGELOG = {
    "4.0.0": ["修复卡顿问题"],
    "3.9.9": ["正式版"],
    "3.9.8": [
        "修复还款：移除Repay多余collateralCoin参数，输入U只还N个",
        "repay_smart 现币优先+USDT抵押品补齐，混合还款无残留",
        "一键还清逐币间隔2秒/148021冲突自动重试3次",
        "还款弹窗宽度缩小，还款ID不再弹窗，还清后3秒刷新持仓",
        "持仓利率列显示时/天/大固标识，利率自动计算",
        "持仓列宽整体收紧，界面更紧凑",
    ],
}
