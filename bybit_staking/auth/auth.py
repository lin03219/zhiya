"""
启动校验模块
IP 白名单验证 + 版本作废检测 + 本地开发绕过
"""
import sys
import json
import urllib.request

from ..version import VERSION

# 你的 Cloudflare Worker 地址，部署后替换这里
# 格式: https://bybit-auth.你的子域.workers.dev
WORKER_URL = "https://bybit-auth.REPLACE_ME.workers.dev"


def isDevMode() -> bool:
    """检测是否为本地开发模式（.py 运行而非 pyinstaller 打包）"""
    return not getattr(sys, "frozen", False)


def getPublicIp() -> str:
    """获取本机公网 IP"""
    try:
        resp = urllib.request.urlopen("https://api.ipify.org", timeout=5)
        return resp.read().decode().strip()
    except Exception:
        return ""


def checkAuth(worker_url: str = "", version: str = "") -> tuple:
    """启动校验
    返回 (通过与否, 原因)
    """
    # 1. 本地开发直接放行
    if isDevMode():
        return True, "dev_bypass"

    url = worker_url or WORKER_URL
    ver = version or VERSION

    # 2. 获取公网 IP
    ip = getPublicIp()
    if not ip:
        return False, "无法获取公网 IP，请检查网络"

    # 3. 请求 Worker 校验
    try:
        full_url = f"{url}?v={ver}"
        resp = urllib.request.urlopen(full_url, timeout=10)
        data = json.loads(resp.read().decode())
        if data.get("allow"):
            return True, "ok"
        reason = data.get("reason", "unknown")
        if reason == "ip_denied":
            return False, f"IP {ip} 未授权，请联系管理员"
        elif reason == "version_outdated":
            return False, "版本已作废，请下载最新版"
        else:
            return False, f"校验失败: {reason}"
    except Exception as e:
        return False, f"校验服务连接失败: {e}"
