"""
版本管理模块
"""
import base64

VERSION = "4.1.1"
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
    "4.1.1": [
        "LTV自动纠错修复：重算改用借币目标LTV，去掉冗余比例",
        "纠错后静默自动重启借币，不弹确认框",
        "借币速率随机范围调整为0.01~0.15秒",
        "LTV刷新统一2秒一次（借币中/非借币）",
        "修复删除借币行导致借币中按钮状态错乱",
        "调整抵押品后双次刷新余额（即时+3秒兜底）",
        "新增配额不足飞书提醒开关",
    ],
    "4.1.0": ["正式版"],
    "3.9.8": [
        "修复还款：移除Repay多余collateralCoin参数，输入U只还N个",
        "repay_smart 现币优先+USDT抵押品补齐，混合还款无残留",
        "一键还清逐币间隔2秒/148021冲突自动重试3次",
        "还款弹窗宽度缩小，还款ID不再弹窗，还清后3秒刷新持仓",
        "持仓利率列显示时/天/大固标识，利率自动计算",
        "持仓列宽整体收紧，界面更紧凑",
    ],
}