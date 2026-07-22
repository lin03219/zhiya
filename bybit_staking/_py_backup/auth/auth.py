"""
启动校验模块
IP 白名单验证 + 本地开发绕过
"""
import sys
import json
import urllib.request

# Cloudflare Worker 地址
WORKER_URL = "https://btbit-auth.lin03219.workers.dev"


def isDevMode() -> bool:
    """本地开发检测"""
    return not (getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"))


def checkAuth() -> tuple:
    """启动校验，返回 (通过与否, 原因)"""
    if isDevMode():
        return True, "dev_bypass"

    req = urllib.request.Request(
        WORKER_URL,
        headers={"User-Agent": "BybitStaking/1.0"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())
        if data.get("allow"):
            return True, "ok"
        ip = data.get("ip", "未知")
        return False, f"IP 不在白名单\nIP={ip}"
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else "(无内容)"
        try:
            data = json.loads(body)
            ip = data.get("ip", "未知")
        except Exception:
            ip = "未知"
        return False, f"HTTP {e.code}\nIP={ip}"
    except Exception as e:
        return False, f"连接失败: {e}"
