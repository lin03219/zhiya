"""
启动校验模块
IP 白名单验证 + 本地开发绕过
"""
import sys
import json
import urllib.request
import socket

# Cloudflare Worker 地址
WORKER_URL = "https://btbit-auth.lin03219.workers.dev"


def isDevMode() -> bool:
    """本地开发检测"""
    return not (getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"))


def getPublicIp() -> str:
    """获取本机公网 IP"""
    try:
        resp = urllib.request.urlopen("https://api.ipify.org", timeout=5)
        return resp.read().decode().strip()
    except Exception as e:
        return f"获取失败: {e}"


def checkAuth() -> tuple:
    """启动校验，返回 (通过与否, 原因)"""
    if isDevMode():
        return True, "dev_bypass"

    ip = getPublicIp()
    if ip.startswith("获取失败"):
        return False, f"无法获取公网 IP\n{ip}"

    # 加 User-Agent 防止被 Cloudflare 当机器人拦截
    req = urllib.request.Request(
        WORKER_URL,
        headers={"User-Agent": "BybitStaking/1.0"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        body = resp.read().decode()
        data = json.loads(body)
        if data.get("allow"):
            return True, "ok"
        return False, f"拒绝\nIP={ip}\n{body}"
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else "(无内容)"
        return False, f"HTTP {e.code}\nIP={ip}\n{body}"
    except Exception as e:
        return False, f"连接失败: {e}\nIP={ip}"
