"""
桌面主界面 — 简洁版
左侧信息栏 + 右侧操作区 + 弹窗（设置、持仓、划转）
"""
import tkinter as tk
import json
from datetime import datetime, timedelta
from collections import deque
from tkinter import ttk, messagebox
import threading
import time
from dataclasses import dataclass
import ctypes
import ctypes.wintypes
from typing import Optional

from ..config.config_manager import ConfigManager, AppConfig
from ..version import VERSION, UPDATE_URL, RELEASES_URL, CHANGELOG, get_download_url
from ..api.bybit_client import BybitClient, BybitApiError, VpnStatus, ApiRateLimit
from ..business.staking_service import StakingService
from ..business.exchange_service import ExchangeService
from ..business.protect_service import ProtectService
from .exchange_window import ExchangeWindow
from ..notify.notifier import Notifier
from ..logging.bitable_logger import log_borrow_success


def _center_window(win: tk.Toplevel, parent: tk.Tk):
    """将弹窗居中于父窗口"""
    win.update_idletasks()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    ww = win.winfo_width()
    wh = win.winfo_height()
    x = px + (pw - ww) // 2
    y = py + (ph - wh) // 2
    win.geometry(f"+{x}+{y}")


def _confirm_dialog(parent, title: str, message: str) -> bool:
    """居中于父窗口的确认弹窗（替代 askyesno）"""
    result = tk.BooleanVar(value=False)
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.resizable(False, False)
    dlg.transient(parent)
    dlg.grab_set()
    f = ttk.Frame(dlg, padding=15)
    f.pack(fill=tk.BOTH, expand=True)
    ttk.Label(f, text=message, font=("", 10)).pack(pady=(0, 15))
    btns = ttk.Frame(f)
    btns.pack()
    ttk.Button(btns, text="是", width=8, command=lambda: (result.set(True), dlg.destroy())).pack(side=tk.LEFT, padx=5)
    ttk.Button(btns, text="否", width=8, command=dlg.destroy).pack(side=tk.LEFT, padx=5)
    dlg.update_idletasks()
    _center_window(dlg, parent)
    dlg.wait_window()
    return result.get()


def _fmt_usd(value: float) -> str:
    """格式化 USD 金额（2 位小数）"""
    if value >= 10000:
        return f"${value:,.2f}"
    elif value >= 1:
        return f"${value:,.2f}"
    else:
        return "$0.00"



@dataclass
class CoinRow:
    """借币行数据"""
    index: int = 0
    coin_var: object = None
    amount_var: object = None
    calc_var: object = None
    calc_label: object = None
    borrow_btn: object = None
    calc_btn: object = None
    looping: bool = False
    fail_count: int = 0
    notifying: bool = False
    ack_data: object = None
    last_coin: str = ""
    auto_filling: bool = False
    calc_after_id: object = None
    frame: object = None
    last_quota_warn: float = 0.0  # 平台配额不足飞书上次推送时间
    quota_fail_count: int = 0  # 配额连续失败计数



class ToolTip:
    """鼠标悬停提示"""
    def __init__(self, widget, text):
        self._widget = widget
        self._text = text
        self._tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)
    def _show(self, event):
        x = event.x_root + 12
        y = event.y_root + 12
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        ttk.Label(self._tip, text=self._text, background="#ffffcc",
                  relief="solid", borderwidth=1, font=("", 8), padding=(4, 2)).pack()
    def _hide(self, event):
        if self._tip:
            self._tip.destroy()
            self._tip = None


class BorrowSettingsDialog(tk.Toplevel):
    """借币设置弹窗（合并保护、LTV纠错、LTV飞书提醒、借币参数）"""
    def __init__(self, parent, config_manager, on_save_callback=None):
        super().__init__(parent)
        self._config = config_manager.get_config()
        self._cm = config_manager
        self._on_save_cb = on_save_callback
        self.title("借币设置")
        self.resizable(False, False)
        self.transient(parent)
        self._build()
        _center_window(self, parent)
        self.update_idletasks()
        w = self.winfo_reqwidth() + 100
        self.minsize(w, 1)

    def _build(self):
        pad = {"padx": 10, "pady": 5}
        hint_font = ("", 7)
        hint_color = "#6b7280"

        f = ttk.Frame(self, padding=8)
        f.pack(fill=tk.BOTH, expand=True)

        # 两列容器
        cols = ttk.Frame(f)
        cols.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(cols)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        right = ttk.Frame(cols)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ===== 左列：借币参数 =====
        param_frame = ttk.LabelFrame(left, text="借币参数", padding=6)
        param_frame.pack(fill=tk.X, pady=(0, 6))

        # 借币目标 LTV
        _tip = ttk.Label(param_frame, text="借币目标 LTV:")
        _tip.pack(anchor=tk.W)
        ToolTip(_tip, "借到后账户LTV目标值(5~78)")
        ltv_row = ttk.Frame(param_frame)
        ltv_row.pack(fill=tk.X, pady=(2, 0))
        self._target_ltv = ttk.Spinbox(ltv_row, from_=5, to=78, width=6)
        self._target_ltv.pack(side=tk.LEFT)
        self._target_ltv.delete(0, tk.END)
        self._target_ltv.insert(0, str(int(self._config.borrow_target_ltv)))

        # 借币请求速率
        _tip = ttk.Label(param_frame, text="借币请求速率:")
        _tip.pack(anchor=tk.W)
        ToolTip(_tip, "间隔+随机0.01~0.15秒防限流")
        rate_row = ttk.Frame(param_frame)
        rate_row.pack(fill=tk.X, pady=(2, 0))
        self._rate_var = tk.StringVar(value=str(self._config.borrow_rate))
        rate_vals = [f"{x/10:.1f}" for x in range(10, 41, 1)]
        self._rate_combo = ttk.Combobox(rate_row, textvariable=self._rate_var,
            values=rate_vals, width=6, state="readonly")
        self._rate_combo.pack(side=tk.LEFT)
        ttk.Label(rate_row, text="秒", foreground=hint_color, font=hint_font).pack(side=tk.LEFT, padx=4)

        # ===== 左列：LTV 自动保护 =====
        protect_cfg = self._config.protect
        protect_frame = ttk.LabelFrame(left, text="LTV 自动保护", padding=6)
        protect_frame.pack(fill=tk.X, pady=(0, 6))

        self._protect_enabled = tk.BooleanVar(value=protect_cfg.enabled)
        _cb = ttk.Checkbutton(protect_frame, text="保护开关", variable=self._protect_enabled)
        _cb.pack(anchor=tk.W)
        ToolTip(_cb, "开启后LTV超阈值自动划转")

        _tip = ttk.Label(protect_frame, text="触发阈值:")

        _tip.pack(anchor=tk.W)

        ToolTip(_tip, "LTV超过此值触发保护")
        trig_row = ttk.Frame(protect_frame)
        trig_row.pack(fill=tk.X, pady=(2, 0))
        self._trigger_ltv = ttk.Entry(trig_row, width=8)
        self._trigger_ltv.pack(side=tk.LEFT)
        self._trigger_ltv.insert(0, str(protect_cfg.trigger_ltv))
        ttk.Label(trig_row, text="%", foreground=hint_color, font=hint_font).pack(side=tk.LEFT, padx=4)

        _tip = ttk.Label(protect_frame, text="单次划转:")

        _tip.pack(anchor=tk.W)

        ToolTip(_tip, "每次自动划转USDT数量")
        per_row = ttk.Frame(protect_frame)
        per_row.pack(fill=tk.X, pady=(2, 0))
        self._per_amount = ttk.Entry(per_row, width=8)
        self._per_amount.pack(side=tk.LEFT)
        self._per_amount.insert(0, protect_cfg.per_transfer_amount)
        ttk.Label(per_row, text="USDT", foreground=hint_color, font=hint_font).pack(side=tk.LEFT, padx=4)

        _tip = ttk.Label(protect_frame, text="最低余额:")

        _tip.pack(anchor=tk.W)

        ToolTip(_tip, "统一账户低于此值不划转")
        min_row = ttk.Frame(protect_frame)
        min_row.pack(fill=tk.X, pady=(2, 0))
        self._min_balance = ttk.Entry(min_row, width=8)
        self._min_balance.pack(side=tk.LEFT)
        self._min_balance.insert(0, protect_cfg.min_unified_balance)
        ttk.Label(min_row, text="USDT", foreground=hint_color, font=hint_font).pack(side=tk.LEFT, padx=4)

        # ===== 右列：LTV 飞书提醒 =====
        alert_cfg = self._config.notify
        alert_frame = ttk.LabelFrame(right, text="LTV 飞书提醒", padding=6)
        alert_frame.pack(fill=tk.X, pady=(0, 6))

        _tip = ttk.Label(alert_frame, text="LTV 提醒阈值:")

        _tip.pack(anchor=tk.W)

        ToolTip(_tip, "LTV超过此值飞书推送告警")
        thr_row = ttk.Frame(alert_frame)
        thr_row.pack(fill=tk.X, pady=(2, 0))
        self._ltv_threshold = ttk.Entry(thr_row, width=8)
        self._ltv_threshold.pack(side=tk.LEFT)
        self._ltv_threshold.insert(0, str(alert_cfg.ltv_threshold))
        ttk.Label(thr_row, text="%", foreground=hint_color, font=hint_font).pack(side=tk.LEFT, padx=4)

        _tip = ttk.Label(alert_frame, text="推送间隔:")

        _tip.pack(anchor=tk.W)

        ToolTip(_tip, "两次告警最小间隔")
        int_row = ttk.Frame(alert_frame)
        int_row.pack(fill=tk.X, pady=(2, 0))
        self._ltv_interval = ttk.Entry(int_row, width=8)
        self._ltv_interval.pack(side=tk.LEFT)
        self._ltv_interval.insert(0, str(alert_cfg.ltv_alert_interval))
        ttk.Label(int_row, text="秒", foreground=hint_color, font=hint_font).pack(side=tk.LEFT, padx=4)

        self._quota_feishu = tk.BooleanVar(value=alert_cfg.quota_feishu_enabled)
        _cb = ttk.Checkbutton(alert_frame, text="配额不足飞书提醒", variable=self._quota_feishu)
        _cb.pack(anchor=tk.W, pady=(4, 0))
        ToolTip(_cb, "连续3次配额不足时飞书推送")

        # ===== 右列：LTV 自动纠错 =====
        correct_cfg = self._config.ltv_correct
        correct_frame = ttk.LabelFrame(right, text="LTV 自动纠错", padding=6)
        correct_frame.pack(fill=tk.X, pady=(0, 6))

        self._correct_enabled = tk.BooleanVar(value=correct_cfg.enabled)
        _cb = ttk.Checkbutton(correct_frame, text="纠错开关", variable=self._correct_enabled)
        _cb.pack(anchor=tk.W)
        ToolTip(_cb, "借币连续失败自动重算")

        _tip = ttk.Label(correct_frame, text="连续失败次数:")

        _tip.pack(anchor=tk.W)

        ToolTip(_tip, "连续失败N次触发纠错")
        cnt_row = ttk.Frame(correct_frame)
        cnt_row.pack(fill=tk.X, pady=(2, 0))
        self._trigger_count = ttk.Spinbox(cnt_row, from_=1, to=10, width=6)
        self._trigger_count.pack(side=tk.LEFT)
        self._trigger_count.delete(0, tk.END)
        self._trigger_count.insert(0, str(correct_cfg.trigger_count))
        ttk.Label(cnt_row, text="次", foreground=hint_color, font=hint_font).pack(side=tk.LEFT, padx=4)

        _tip = ttk.Label(correct_frame, text="等待时间:")

        _tip.pack(anchor=tk.W)

        ToolTip(_tip, "触发后等待再重算")
        wait_row = ttk.Frame(correct_frame)
        wait_row.pack(fill=tk.X, pady=(2, 0))
        self._wait_seconds = ttk.Spinbox(wait_row, from_=1, to=120, width=6)
        self._wait_seconds.pack(side=tk.LEFT)
        self._wait_seconds.delete(0, tk.END)
        self._wait_seconds.insert(0, str(correct_cfg.wait_seconds))
        ttk.Label(wait_row, text="秒", foreground=hint_color, font=hint_font).pack(side=tk.LEFT, padx=4)

        self._auto_restart = tk.BooleanVar(value=correct_cfg.auto_restart)
        _cb = ttk.Checkbutton(correct_frame, text="自动重新发起", variable=self._auto_restart)
        _cb.pack(anchor=tk.W)
        ToolTip(_cb, "按LTV%重算后自动发起借币")

        # 保存/取消
        btn_row = ttk.Frame(f)
        btn_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_row, text="保存", command=self._on_save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_row, text="取消", command=self.destroy).pack(side=tk.RIGHT)

    def _on_save(self):
        try:
            # 借币参数
            target_ltv = max(5, min(78, float(self._target_ltv.get())))
            self._cm.set_borrow_target_ltv(target_ltv)
            self._cm.set_borrow_rate(float(self._rate_var.get()))

            # LTV 自动保护
            trigger_ltv = float(self._trigger_ltv.get().strip() or "70")
            per_amount = self._per_amount.get().strip() or "100"
            min_balance = self._min_balance.get().strip() or "500"
            self._cm.set_protect(self._protect_enabled.get(), trigger_ltv, per_amount, min_balance)

            # LTV 飞书提醒
            ltv_str = self._ltv_threshold.get().strip()
            if ltv_str:
                self._cm.set_ltv_threshold(float(ltv_str))
            interval = max(1, int(self._ltv_interval.get() or "60"))
            self._cm.set_ltv_alert_interval(interval)
            self._cm.set_quota_feishu_enabled(self._quota_feishu.get())

            # LTV 自动纠错
            self._cm.set_ltv_correct(
                enabled=self._correct_enabled.get(),
                trigger_count=int(self._trigger_count.get()),
                wait_seconds=int(self._wait_seconds.get()),
                auto_restart=self._auto_restart.get(),
                redundancy_ratio=85.0,
            )

            self._cm.save()
            self.destroy()
            if self._on_save_cb:
                self._on_save_cb()
        except ValueError:
            import tkinter.messagebox as mb
            mb.showerror("保存失败", "请输入有效的数值", parent=self)
        except Exception as e:
            import tkinter.messagebox as mb
            mb.showerror("保存失败", str(e))


class SettingsDialog(tk.Toplevel):
    """设置弹窗（非模态）"""

    def __init__(self, parent, config_manager: ConfigManager, on_save_callback):
        super().__init__(parent)
        self._config_manager = config_manager
        self._config = config_manager.get_config()
        self._on_save = on_save_callback

        self.title("设置")
        self.resizable(False, False)
        self.transient(parent)

        self._build()
        _center_window(self, parent)
        self.update_idletasks()
        w = self.winfo_reqwidth() + 100
        self.minsize(w, 1)

    def _build(self):
        pad = {"padx": 10, "pady": 5}

        api_frame = ttk.LabelFrame(self, text="Bybit API 密钥", padding=10)
        api_frame.pack(fill=tk.X, **pad)

        ttk.Label(api_frame, text="API Key:").pack(anchor=tk.W)
        self._api_key = ttk.Entry(api_frame, width=55, show="*")
        self._api_key.pack(fill=tk.X, pady=2)
        self._api_key.insert(0, self._config.api_key)

        ttk.Label(api_frame, text="API Secret:").pack(anchor=tk.W)
        self._api_secret = ttk.Entry(api_frame, width=55, show="*")
        self._api_secret.pack(fill=tk.X, pady=2)
        self._api_secret.insert(0, self._config.api_secret)

        net_row = ttk.Frame(api_frame)
        net_row.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(net_row, text="网络:").pack(side=tk.LEFT)
        self._network_var = tk.StringVar(value=self._config.network)
        ttk.Radiobutton(net_row, text="主网", variable=self._network_var, value="mainnet").pack(
            side=tk.LEFT, padx=10
        )
        ttk.Radiobutton(net_row, text="测试网", variable=self._network_var, value="testnet").pack(
            side=tk.LEFT
        )

        proxy_frame = ttk.LabelFrame(self, text="代理设置", padding=10)
        proxy_frame.pack(fill=tk.X, **pad)

        self._proxy_enabled = tk.BooleanVar(value=self._config.proxy.enabled)
        ttk.Checkbutton(proxy_frame, text="启用代理", variable=self._proxy_enabled).pack(anchor=tk.W)

        ttk.Label(proxy_frame, text="HTTP / HTTPS 代理:").pack(anchor=tk.W)
        self._proxy_http = ttk.Entry(proxy_frame, width=55)
        self._proxy_http.pack(fill=tk.X, pady=2)
        proxy_val = self._config.proxy.http or self._config.proxy.https
        self._proxy_http.insert(0, proxy_val)

        notify_frame = ttk.LabelFrame(self, text="通知 Webhook", padding=10)
        notify_frame.pack(fill=tk.X, **pad)

        ttk.Label(notify_frame, text="飞书:").pack(anchor=tk.W)
        self._feishu = ttk.Entry(notify_frame, width=55)
        self._feishu.pack(fill=tk.X, pady=2)
        self._feishu.insert(0, self._config.notify.feishu_webhook)

        ttk.Label(notify_frame, text="钉钉:").pack(anchor=tk.W)
        self._dingtalk = ttk.Entry(notify_frame, width=55)
        self._dingtalk.pack(fill=tk.X, pady=2)
        self._dingtalk.insert(0, self._config.notify.dingtalk_webhook)


        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, pady=(10, 5), padx=10)
        ttk.Button(btn_row, text="保存", command=self._save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_row, text="取消", command=self.destroy).pack(side=tk.RIGHT)

    def _save(self):
        try:
            self._config_manager.set_api_credentials(
                self._api_key.get().strip(),
                self._api_secret.get().strip(),
            )
            self._config_manager.set_network(self._network_var.get())
            self._config_manager.set_proxy(
                http=self._proxy_http.get().strip(),
                https=self._proxy_http.get().strip(),
                enabled=self._proxy_enabled.get(),
            )
            self._config_manager.set_notify(
                feishu_webhook=self._feishu.get().strip(),
                dingtalk_webhook=self._dingtalk.get().strip(),
            )
            self._config_manager.save()
            self._on_save()
            self.destroy()
        except Exception as e:
            import tkinter.messagebox as mb
            mb.showerror("保存失败", str(e))




class RepayDialog(tk.Toplevel):
    """还币弹窗 — 手动输入币数还款"""
    def __init__(self, parent, service, coin, debt_amount, on_success=None, log_func=None):
        super().__init__(parent)
        self._service = service
        self._coin = coin
        self._debt = debt_amount
        self._on_success = on_success
        self._log_func = log_func
        self.title(f"还款 — {coin}")
        self.resizable(False, False)
        self.transient(parent)
        self._build()
        _center_window(self, parent)
        self.update_idletasks()
        w = self.winfo_reqwidth() + 0
        self.minsize(w, 1)

    def _build(self):
        pad = {"padx": 10, "pady": 5}
        ttk.Label(self, text=f"币种: {self._coin}", font=("", 10, "bold")).pack(pady=(10, 5))
        info = ttk.Frame(self)
        info.pack(fill=tk.X, **pad)
        ttk.Label(info, text="欠款总额:", width=8).pack(side=tk.LEFT)
        ttk.Label(info, text=self._debt, foreground="#d97706", font=("", 9, "bold")).pack(side=tk.LEFT)

        row = ttk.Frame(self)
        row.pack(fill=tk.X, **pad)
        ttk.Label(row, text="还款数量:", width=8).pack(side=tk.LEFT)
        self._amount = ttk.Entry(row, width=16)
        self._amount.pack(side=tk.LEFT, padx=5)
        ttk.Button(row, text="全部", width=5, command=self._fill_all).pack(side=tk.LEFT)

        ttk.Button(self, text="确定还款", command=self._do_repay).pack(pady=(5, 10))

    def _fill_all(self):
        self._amount.delete(0, tk.END)
        self._amount.insert(0, self._debt)

    def _do_repay(self):
        amt = self._amount.get().strip()
        if not amt:
            messagebox.showwarning("提示", "请输入还款数量", parent=self)
            return
        if not messagebox.askyesno("确认还款", f"确定还 {amt} {self._coin}？", parent=self):
            return
        if self._log_func:
            self._log_func(f"还款 {self._coin} {amt} 开始")
        try:
            self._service.repay_smart(self._coin, amt)
            if self._log_func:
                self._log_func(f"还款成功: {self._coin} {amt}")
            if self._on_success:
                self._on_success()
            self.destroy()
        except Exception as e:
            if self._log_func:
                self._log_func(f"还款失败: {self._coin} {amt} - {e}")
            messagebox.showerror("还款失败", str(e), parent=self)

class PositionsWindow(tk.Toplevel):
    def __init__(self, parent, service, log_func=None):
        super().__init__(parent)
        self._service = service
        self._log_func = log_func
        self._row_frames = []
        self._auto_refresh_id = None
        self.title("当前持仓")
        self.geometry("700x450")
        self.resizable(True, True)
        self.transient(parent)
        self._build()
        _center_window(self, parent)
        if self._service:
            self._refresh()
        self._start_auto_refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if self._auto_refresh_id:
            self.after_cancel(self._auto_refresh_id)
        self.destroy()

    def _start_auto_refresh(self):
        self._refresh()
        self._auto_refresh_id = self.after(5000, self._start_auto_refresh)

    def _build(self):
        pad = {"padx": 10, "pady": 3}
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=10, pady=(10, 2))
        for text, width, anchor in [
            ("借入币种", 8, tk.W),
            ("欠款总额", 11, tk.CENTER),
            ("累计利息", 11, tk.CENTER),
            ("利率/时/天", 22, tk.CENTER),
            ("统一持有", 8, tk.CENTER),
            ("资金持有", 8, tk.CENTER),
            ("操作", 24, tk.CENTER),
        ]:
            ttk.Label(header, text=text, width=width, anchor=anchor, font=("", 9, "bold")).pack(side=tk.LEFT, padx=0)
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)
        cf = ttk.Frame(self)
        cf.pack(fill=tk.BOTH, expand=True, padx=10, pady=2)
        self._canvas = tk.Canvas(cf, height=200, highlightthickness=0)
        sb = ttk.Scrollbar(cf, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._row_container = ttk.Frame(self._canvas)
        self._canvas.create_window((0, 0), window=self._row_container, anchor=tk.NW, tags="container")
        self._row_container.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._summary_var = tk.StringVar(value="抵押品: --  |  总欠款 USD: --  |  LTV: --")
        ttk.Label(self, textvariable=self._summary_var, font=("", 9)).pack(anchor=tk.W, padx=10, pady=3)
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)
        br = ttk.Frame(self)
        br.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(br, text="一键还清全部", command=self._repay_all).pack(side=tk.LEFT, padx=3)
        self._status_var = tk.StringVar(value="")
        ttk.Label(br, textvariable=self._status_var, foreground="#6b7280", font=("", 8)).pack(side=tk.LEFT, padx=10)
        ttk.Button(br, text="刷新", command=self._refresh).pack(side=tk.RIGHT)


    def _refresh(self):
        if not self._service:
            return
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        try:
            pos = self._service.get_position()
            bl = pos.get("borrowList", [])
            cl = pos.get("collateralList", [])
            td = pos.get("totalDebt", "0")
            lr = pos.get("ltv", "")
            ltv = f"{float(lr)*100:.2f}%" if lr else "--"
            unified_map = {}
            fund_map = {}
            try:
                for ub in self._service.get_unified_balance():
                    unified_map[ub.coin] = ub.wallet_balance
            except Exception:
                pass
            try:
                for fb in self._service.get_fund_balance():
                    fund_map[fb.coin] = fb.wallet_balance
            except Exception:
                pass
            initial_map = {}
            try:
                for h in self._service.get_borrow_history(limit=50):
                    c = h.get("loanCoin", "") or h.get("loanCurrency", "")
                    if c and c not in initial_map:
                        initial_map[c] = h.get("initialLoanAmount", "0")
            except Exception:
                pass
            rows_data = []
            for b in bl:
                coin = b.get("loanCurrency", "")
                debt = b.get("flexibleTotalDebt", "0")
                try:
                    init_amt = b.get("initialLoanAmount", "") or initial_map.get(coin, "0")
                    acc_interest = float(debt) - float(init_amt)
                    interest_str = f"{acc_interest:.6f}" if acc_interest >= 0 else "0"
                except Exception:
                    interest_str = "--"
                # 利率: 灵活(复利) or 固定
                flex_debt = float(b.get("flexibleTotalDebt", "0"))
                fixed_debt = float(b.get("fixedTotalDebt", "0"))
                if flex_debt > 0:
                    hour_rate = float(b.get("flexibleHourlyInterestRate", "0"))
                    hour_pct = hour_rate * 100
                    day_rate = (1 + hour_rate) ** 24 - 1
                    day_pct = day_rate * 100
                    rp = f"{hour_pct:.4f}% · {day_pct:.4f}% 复"
                elif fixed_debt > 0:
                    rp = f"-- 固"
                else:
                    rp = "--"
                rows_data.append((coin, debt, interest_str, rp, unified_map.get(coin, "0"), fund_map.get(coin, "0")))
            cs = ", ".join(f"{c.get('currency', '')}: {c.get('amount', '')}" for c in cl) or "--"
            summary = f"抵押品: {cs}  |  总欠款 USD: ${td}  |  LTV: {ltv}"

            def update_ui():
                for f in self._row_frames:
                    f.destroy()
                self._row_frames.clear()
                if not rows_data:
                    ttk.Label(self._row_container, text="暂无借币持仓", foreground="gray").pack(pady=20)
                for coin, debt, interest_str, rp, uni_bal, fund_bal in rows_data:
                    row = ttk.Frame(self._row_container)
                    row.pack(fill=tk.X, pady=1)
                    self._row_frames.append(row)
                    ttk.Label(row, text=coin, width=8, anchor=tk.W).pack(side=tk.LEFT, padx=0)
                    ttk.Label(row, text=debt, width=11, anchor=tk.CENTER).pack(side=tk.LEFT, padx=0)
                    ttk.Label(row, text=interest_str, width=11, anchor=tk.CENTER, foreground="#ef4444").pack(side=tk.LEFT, padx=0)
                    ttk.Label(row, text=rp, width=22, anchor=tk.CENTER).pack(side=tk.LEFT, padx=0)
                    ttk.Label(row, text=uni_bal, width=8, anchor=tk.CENTER).pack(side=tk.LEFT, padx=0)
                    ttk.Label(row, text=fund_bal, width=8, anchor=tk.CENTER).pack(side=tk.LEFT, padx=0)
                    op = ttk.Frame(row)
                    op.pack(side=tk.LEFT, padx=1, fill=tk.X, expand=True)
                    ttk.Button(op, text="划转", width=5, command=lambda c=coin: self._transfer_coin(c)).pack(side=tk.LEFT, padx=2)
                    ttk.Button(op, text="还款", width=5, command=lambda c=coin: self._repay_coin(c)).pack(side=tk.LEFT, padx=2)
                    ttk.Button(op, text="还清", width=5, command=lambda c=coin: self._repay_clear_coin(c)).pack(side=tk.LEFT, padx=2)
                self._summary_var.set(summary)
                self._status_var.set("")
            self.after(0, update_ui)
        except BybitApiError as e:
            self.after(0, lambda e=e: messagebox.showerror("查询失败", str(e), parent=self))

    def _transfer_coin(self, coin):
        dlg = TransferDialog(self, self._service, on_success=self._refresh, log_func=self._log_func)
        dlg._coin.set(coin)

    def _repay_coin(self, coin):
        """打开还款弹窗（手动填币数）"""
        debt = "0"
        try:
            pos = self._service.get_position()
            for b in pos.get("borrowList", []):
                if b.get("loanCurrency") == coin:
                    debt = b.get("flexibleTotalDebt", "0")
                    break
        except Exception:
            pass
        RepayDialog(self, self._service, coin, debt, on_success=self._refresh, log_func=self._log_func)

    def _repay_clear_coin(self, coin):
        """还清单个币种：先划转资金账户该币 → 再用币还本金 → 利息走 USDT 抵押品"""
        if not self._service:
            return
        try:
            pos = self._service.get_position()
            debt = "0"
            for b in pos.get("borrowList", []):
                if b.get("loanCurrency") == coin:
                    debt = b.get("flexibleTotalDebt", "0")
                    break
            if debt == "0" or float(debt) <= 0:
                messagebox.showinfo("提示", f"{coin} 已无欠款", parent=self)
                return
            if not messagebox.askyesno("确认还清", f"确定还清 {coin}？\n欠款总额: {debt}", parent=self):
                return
            if self._log_func:
                self._log_func(f"还清 {coin} {debt} 开始")
            threading.Thread(target=self._run_repay_clear, args=(coin, debt), daemon=True).start()
        except Exception as e:
            messagebox.showerror("错误", str(e), parent=self)

    def _run_repay_clear(self, coin, debt):
        """后台还清单币 - 直接调用 repay_smart 全额还清"""
        self.after(0, lambda: self._status_var.set(f"正在还清 {coin}..."))
        try:
            self._service.repay_smart(coin, debt)
            if self._log_func:
                self._log_func(f"还清成功: {coin} {debt}")
            self.after(0, lambda: self._status_var.set(f"{coin} 还清成功"))
            self.after(0, lambda: messagebox.showinfo("还清成功", f"{coin} 已还清", parent=self))
            self.after(3000, self._refresh)
        except Exception as e:
            if self._log_func:
                self._log_func(f"还清失败: {coin} {debt} - {e}")
            self.after(0, lambda: self._status_var.set(f"{coin} 还清失败"))
            self.after(0, lambda e=e: messagebox.showerror("还清失败", f"{coin}: {e}", parent=self))

    def _repay_all(self):
        """一键还清全部（有确认弹窗 + 后台异步 + 结果统计）"""
        if not self._service:
            return
        try:
            pos = self._service.get_position()
            bl = pos.get("borrowList", [])
            if not bl:
                messagebox.showinfo("提示", "暂无借币持仓", parent=self)
                return
            lines = ["确定还清以下全部币种？", ""]
            for b in bl:
                coin = b.get("loanCurrency", "")
                debt = b.get("flexibleTotalDebt", "0")
                lines.append(f"  {coin}: {debt}")
            lines.append("")
            lines.append(f"共 {len(bl)} 个币种")
            if not messagebox.askyesno("确认一键还清全部", "\n".join(lines), parent=self):
                return
            if self._log_func:
                self._log_func(f"一键还清全部 开始 ({len(bl)}币种)")
            threading.Thread(target=self._run_repay_all, args=(bl,), daemon=True).start()
        except Exception as e:
            messagebox.showerror("失败", str(e), parent=self)

    def _run_repay_all(self, bl):
        """后台逐币还清"""
        total = len(bl)
        success = []
        failed = []
        for i, b in enumerate(bl):
            coin = b.get("loanCurrency", "")
            debt = b.get("flexibleTotalDebt", "0")
            self.after(0, lambda c=coin, n=i + 1: self._status_var.set(f"正在还 {c}… ({n}/{total})"))
            ok = False
            last_err = None
            for attempt in range(3):
                try:
                    self._service.repay_smart(coin, debt)
                    success.append(coin)
                    ok = True
                    if self._log_func:
                        self._log_func(f"还清成功: {coin} {debt}")
                    break
                except BybitApiError as e:
                    if e.code == 148021 and attempt < 2:
                        last_err = e
                        time.sleep(3)
                        continue
                    last_err = e
                    break
                except Exception as e:
                    last_err = e
                    break
            if not ok:
                failed.append(f"{coin}: {last_err}")
                if self._log_func:
                    self._log_func(f"还清失败: {coin} {debt} - {last_err}")
            time.sleep(2)

        def show_result():
            self._status_var.set("")
            parts = []
            if success:
                parts.append(f"成功: {', '.join(success)}")
            if failed:
                parts.append(f"失败: {', '.join(failed)}")
            title = "全部还清" if not failed else "部分还清"
            if self._log_func:
                self._log_func(f"一键还清完成 成功{len(success)}/失败{len(failed)}")
            messagebox.showinfo(title, "\n".join(parts), parent=self)
            self.after(3000, self._refresh)
        self.after(0, show_result)

class TransferDialog(tk.Toplevel):
    """划转弹窗 — 统一账户 ↔ 资金账户"""

    def __init__(self, parent, service: Optional[StakingService], on_success=None, log_func=None):
        super().__init__(parent)
        self._service = service
        self._log_func = log_func
        self._on_success = on_success
        self.title("账内划转 — 统一 ↔ 资金")
        self.resizable(False, False)
        self.transient(parent)

        self._build()
        _center_window(self, parent)
        self.update_idletasks()
        w = self.winfo_reqwidth() + 0
        self.minsize(w, 1)

    def _build(self):
        pad = {"padx": 10, "pady": 5}

        ttk.Label(self, text="统一账户  ←→  资金账户", font=("", 10, "bold")).pack(pady=(10, 5))

        dir_frame = ttk.Frame(self)
        dir_frame.pack(fill=tk.X, **pad)
        ttk.Label(dir_frame, text="方向:", width=6).pack(side=tk.LEFT)
        self._direction = tk.StringVar(value="UNIFIED_TO_FUND")
        ttk.Radiobutton(
            dir_frame, text="统一 → 资金", variable=self._direction, value="UNIFIED_TO_FUND"
        ).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(
            dir_frame, text="资金 → 统一", variable=self._direction, value="FUND_TO_UNIFIED"
        ).pack(side=tk.LEFT)

        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X, **pad)
        ttk.Label(row1, text="币种:", width=6).pack(side=tk.LEFT)
        self._coin = ttk.Combobox(row1, values=["USDT", "USDC", "BTC", "ETH", "SOL"], width=12)
        self._coin.pack(side=tk.LEFT, padx=5)
        self._coin.set("USDT")
        ttk.Label(row1, text="数量:", width=6).pack(side=tk.LEFT)
        self._amount = ttk.Entry(row1, width=14)
        self._amount.pack(side=tk.LEFT)
        ttk.Button(row1, text="全部", width=4, command=self._fill_max).pack(side=tk.LEFT, padx=3)

        ttk.Button(self, text="执行划转", command=self._do_transfer).pack(pady=15)

    def _fill_max(self):
        """根据方向自动填入对应账户全部余额"""
        coin = self._coin.get().strip().upper()
        if not coin or not self._service:
            return
        try:
            direction = self._direction.get()
            if direction == "UNIFIED_TO_FUND":
                balances = self._service.get_unified_balance(coin)
            else:
                balances = self._service.get_fund_balance(coin)
            # 精确匹配币种，取该币种的余额
            for b in balances:
                if b.coin.upper() == coin:
                    self._amount.delete(0, tk.END)
                    self._amount.insert(0, b.wallet_balance)
                    return
        except Exception:
            pass

    def _do_transfer(self):
        if not self._service:
            messagebox.showwarning("提示", "请先配置 API 密钥", parent=self)
            return
        coin = self._coin.get().strip().upper()
        amount = self._amount.get().strip()
        if not coin or not amount:
            messagebox.showwarning("提示", "请填写币种和数量", parent=self)
            return

        direction = self._direction.get()
        if direction == "UNIFIED_TO_FUND":
            from_acc, to_acc = "UNIFIED", "FUND"
            label = f"统一 → 资金: {amount} {coin}"
        else:
            from_acc, to_acc = "FUND", "UNIFIED"
            label = f"资金 → 统一: {amount} {coin}"

        if not _confirm_dialog(self, "确认划转", label):
            return
        c, a, f, t = coin, amount, from_acc, to_acc
        if self._log_func:
            self._log_func(f"划转 {amount} {coin} {from_acc} -> {to_acc} 开始")
        threading.Thread(target=self._run_transfer, args=(c, a, f, t), daemon=True).start()

    def _run_transfer(self, coin, amount, from_acc, to_acc):
        try:
            tid = self._service.transfer(coin, amount, from_acc, to_acc)
            if self._log_func:
                self._log_func(f"划转成功: {amount} {coin} {from_acc} -> {to_acc} (tid={tid})")
            if self._on_success:
                self.after(0, self._on_success)
        except BybitApiError as e:
            if self._log_func:
                self._log_func(f"划转失败: {amount} {coin} {from_acc} -> {to_acc} - {e}")
            self.after(0, lambda e=e: messagebox.showerror("划转失败", str(e), parent=self))

class ProtectDialog(tk.Toplevel):
    """保护参数设置弹窗"""

    def __init__(self, parent, config_manager: ConfigManager, on_save_callback):
        super().__init__(parent)
        self._config_manager = config_manager
        self._config = config_manager.get_config()
        self._on_save = on_save_callback

        self.title("保护设置")
        self.resizable(False, False)
        self.transient(parent)

        self._build()
        _center_window(self, parent)
        self.update_idletasks()
        w = self.winfo_reqwidth() + 100
        self.minsize(w, 1)

    def _build(self):
        pad = {"padx": 10, "pady": 5}

        sw_frame = ttk.Frame(self)
        sw_frame.pack(fill=tk.X, **pad)
        self._enabled_var = tk.BooleanVar(value=self._config.protect.enabled)
        ttk.Checkbutton(sw_frame, text="启用自动保护", variable=self._enabled_var).pack(anchor=tk.W)

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=5)

        trigger_frame = ttk.LabelFrame(self, text="触发条件", padding=10)
        trigger_frame.pack(fill=tk.X, **pad)

        ttk.Label(trigger_frame, text="LTV 高于 (%):").pack(anchor=tk.W)
        self._trigger_ltv = ttk.Entry(trigger_frame, width=10)
        self._trigger_ltv.pack(anchor=tk.W, pady=2)
        self._trigger_ltv.insert(0, str(self._config.protect.trigger_ltv))
        ttk.Label(trigger_frame, text="主页 LTV 超过此值自动追加抵押", foreground="#6b7280",
                  font=("", 8)).pack(anchor=tk.W)

        transfer_frame = ttk.LabelFrame(self, text="划转参数", padding=10)
        transfer_frame.pack(fill=tk.X, **pad)

        ttk.Label(transfer_frame, text="单笔划转金额 (USDT):").pack(anchor=tk.W)
        self._per_amount = ttk.Entry(transfer_frame, width=15)
        self._per_amount.pack(anchor=tk.W, pady=2)
        self._per_amount.insert(0, self._config.protect.per_transfer_amount)
        ttk.Label(transfer_frame, text="每次自动划转并追加抵押的 USDT 数量", foreground="#6b7280",
                  font=("", 8)).pack(anchor=tk.W)

        ttk.Label(transfer_frame, text="统一账户最低余额 (USDT):").pack(anchor=tk.W, pady=(8, 0))
        self._min_balance = ttk.Entry(transfer_frame, width=15)
        self._min_balance.pack(anchor=tk.W, pady=2)
        self._min_balance.insert(0, self._config.protect.min_unified_balance)
        ttk.Label(transfer_frame, text="统一账户 USDT 低于此值则停止划转, 飞书告警",
                  foreground="#6b7280", font=("", 8)).pack(anchor=tk.W)

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=5)
        note = ttk.Label(self, text="⚠ 每次 LTV 刷新检测到超标即触发, 成功或失败均飞书通知",
                         foreground="#d97706", font=("", 8), wraplength=300)
        note.pack(fill=tk.X, padx=10, pady=(0, 5))

        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, pady=(0, 5), padx=10)
        ttk.Button(btn_row, text="保存", command=self._save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_row, text="取消", command=self.destroy).pack(side=tk.RIGHT)

    def _save(self):
        try:
            trigger_ltv = float(self._trigger_ltv.get().strip() or "70")
            per_amount = self._per_amount.get().strip() or "100"
            min_balance = self._min_balance.get().strip() or "500"
            enabled = self._enabled_var.get()

            self._config_manager.set_protect(enabled, trigger_ltv, per_amount, min_balance)
            self._config_manager.save()
            self._on_save()
            self.destroy()
        except ValueError:
            messagebox.showerror("保存失败", "请输入有效的数值", parent=self)
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self)


class AdjustCollateralDialog(tk.Toplevel):
    """调整抵押品弹窗"""
    def __init__(self, parent, service, config_manager, pos_data, fund_usdt, on_success=None, main_window=None, ltv_var=None):
        super().__init__(parent)
        self._service = service
        self._config = config_manager.get_config()
        self._on_success = on_success
        self._main_window = main_window
        self._shared_ltv_var = ltv_var
        # 首页LTV变化时同步更新抵押品/负债数据并重算预估
        if self._shared_ltv_var:
            self._shared_ltv_var.trace_add("write", self._on_ltv_changed)
        self.title("调整抵押品")
        self.resizable(False, False)
        self.transient(parent)
        self._tab = "add"
        self._build()
        self._set_data(pos_data, fund_usdt)
        _center_window(self, parent)
        # 定时刷新LTV（复用首页缓存，不额外消耗API）


    def _build(self):
        pad = {"padx": 10, "pady": 5}

        f = ttk.Frame(self, padding=10)
        f.pack(fill=tk.BOTH, expand=True)

        # Tab 按钮
        tab_row = ttk.Frame(f)
        tab_row.pack(fill=tk.X, pady=(0, 10))
        self._add_tab_btn = tk.Button(tab_row, text="追加抵押资产", font=("", 10),
                                       bg="#3b82f6", fg="white", relief="flat",
                                       command=lambda: self._switch_tab("add"))
        self._add_tab_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self._reduce_tab_btn = tk.Button(tab_row, text="减少抵押资产", font=("", 10),
                                          bg="#e5e7eb", fg="#374151", relief="flat",
                                          command=lambda: self._switch_tab("reduce"))
        self._reduce_tab_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        # 数据区
        data_frame = ttk.LabelFrame(f, text="持仓概览", padding=8)
        data_frame.pack(fill=tk.X, pady=(0, 8))

        _r1 = ttk.Frame(data_frame)
        _r1.pack(fill=tk.X)
        _lbl1 = ttk.Label(_r1, text="当前 LTV:", width=14, anchor=tk.W)
        _lbl1.pack(side=tk.LEFT)
        ToolTip(_lbl1, "当前持仓贷款价值比")
        _ltv_tv = self._shared_ltv_var if self._shared_ltv_var else tk.StringVar(value="--")
        self._ltv_val = ttk.Label(_r1, textvariable=_ltv_tv, font=("", 10, "bold"), foreground="#d97706")
        self._ltv_val.pack(side=tk.LEFT)

        _r2 = ttk.Frame(data_frame)
        _r2.pack(fill=tk.X, pady=(2, 0))
        _lbl2 = ttk.Label(_r2, text="总抵押品价值:", width=14, anchor=tk.W)
        _lbl2.pack(side=tk.LEFT)
        ToolTip(_lbl2, "当前抵押品总价值(USDT)")
        self._collateral_val = ttk.Label(_r2, text="--")
        self._collateral_val.pack(side=tk.LEFT)

        _r3 = ttk.Frame(data_frame)
        _r3.pack(fill=tk.X, pady=(2, 0))
        _lbl3 = ttk.Label(_r3, text="总负债:", width=14, anchor=tk.W)
        _lbl3.pack(side=tk.LEFT)
        ToolTip(_lbl3, "当前借入总额(USDT)")
        self._debt_val = ttk.Label(_r3, text="--")
        self._debt_val.pack(side=tk.LEFT)

        # 可用余额
        self._balance_frame = ttk.LabelFrame(f, text="资金账户", padding=8)
        self._balance_frame.pack(fill=tk.X, pady=(0, 8))
        _bl = ttk.Frame(self._balance_frame)
        _bl.pack(fill=tk.X)
        _lbl4 = ttk.Label(_bl, text="可用余额:", width=14, anchor=tk.W)
        _lbl4.pack(side=tk.LEFT)
        ToolTip(_lbl4, "资金账户中可用USDT余额")
        self._balance_val = ttk.Label(_bl, text="--")
        self._balance_val.pack(side=tk.LEFT)

        # 金额输入
        amount_frame = ttk.LabelFrame(f, text="划转金额", padding=8)
        amount_frame.pack(fill=tk.X, pady=(0, 8))
        _ar = ttk.Frame(amount_frame)
        _ar.pack(fill=tk.X)
        _lbl5 = ttk.Label(_ar, text="金额 (USDT):", width=14, anchor=tk.W)
        _lbl5.pack(side=tk.LEFT)
        ToolTip(_lbl5, "输入要追加或减少的USDT金额")
        self._amount_var = tk.StringVar()
        self._amount_entry = ttk.Entry(_ar, textvariable=self._amount_var, width=18)
        self._amount_entry.pack(side=tk.LEFT, padx=(0, 5))
        self._amount_var.trace_add("write", self._on_amount_change)

        # 快捷比例
        pct_row = ttk.Frame(amount_frame)
        pct_row.pack(fill=tk.X, pady=(5, 0))
        self._pct_btns = []
        for pct in [25, 50, 75, 100]:
            btn = ttk.Button(pct_row, text="{0}%".format(pct), width=6,
                           command=lambda p=pct: self._set_pct(p))
            btn.pack(side=tk.LEFT, padx=2)
            self._pct_btns.append(btn)

        # 预估
        est_frame = ttk.LabelFrame(f, text="调整后预计", padding=8)
        est_frame.pack(fill=tk.X, pady=(0, 10))
        _er1 = ttk.Frame(est_frame)
        _er1.pack(fill=tk.X)
        _lbl6 = ttk.Label(_er1, text="抵押品将变动:", width=14, anchor=tk.W)
        _lbl6.pack(side=tk.LEFT)
        ToolTip(_lbl6, "预估抵押品变化量")
        self._collateral_change = ttk.Label(_er1, text="--", foreground="#6b7280")
        self._collateral_change.pack(side=tk.LEFT)

        _er2 = ttk.Frame(est_frame)
        _er2.pack(fill=tk.X, pady=(2, 0))
        _lbl7 = ttk.Label(_er2, text="预估 LTV:", width=14, anchor=tk.W)
        _lbl7.pack(side=tk.LEFT)
        ToolTip(_lbl7, "调整后的预估贷款价值比")
        self._est_ltv = ttk.Label(_er2, text="--", font=("", 10, "bold"), foreground="#10b981")
        self._est_ltv.pack(side=tk.LEFT)

        # 按钮
        btn_row = ttk.Frame(f)
        btn_row.pack(fill=tk.X)
        self._confirm_btn = ttk.Button(btn_row, text="确认追加", command=self._on_confirm)
        self._confirm_btn.pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_row, text="取消", command=self.destroy).pack(side=tk.RIGHT)

    def _switch_tab(self, tab):
        self._tab = tab
        self._amount_var.set("")
        self._collateral_change.config(text="--")
        self._est_ltv.config(text="--")
        if tab == "add":
            self._add_tab_btn.config(bg="#3b82f6", fg="white")
            self._reduce_tab_btn.config(bg="#e5e7eb", fg="#374151")
            self._confirm_btn.config(text="确认追加")
            self._balance_frame.config(text="资金账户")
            self._balance_val.config(text="{:,.2f} USDT".format(self._fund_usdt))
        else:
            self._add_tab_btn.config(bg="#e5e7eb", fg="#374151")
            self._reduce_tab_btn.config(bg="#3b82f6", fg="white")
            self._confirm_btn.config(text="确认减少")
            self._balance_frame.config(text="可释放抵押品")
            self._balance_val.config(text="{:,.2f} USDT".format(self._releasable))


    def _on_ltv_changed(self, *args):
        """首页LTV刷新时同步更新抵押品/负债数据并重算预估"""
        try:
            if self._main_window and hasattr(self._main_window, "_last_pos_data"):
                pos = self._main_window._last_pos_data
                if pos:
                    self._total_collateral = float(pos.get("totalCollateral", "0"))
                    self._total_debt = float(pos.get("totalDebt", "0"))
                    self._collateral_val.config(text="{:,.2f} USDT".format(self._total_collateral))
                    self._debt_val.config(text="{:,.2f} USDT".format(self._total_debt))
                    target_ratio = self._config.borrow_target_ltv / 100.0
                    min_collateral = self._total_debt / target_ratio if target_ratio > 0 else self._total_debt
                    self._releasable = max(0, self._total_collateral - min_collateral)
                    if self._tab == "reduce":
                        self._balance_val.config(text="{:,.2f} USDT".format(self._releasable))
                    self._on_amount_change()
        except Exception:
            pass

    def _set_data(self, pos_data, fund_usdt_in):
        """从首页缓存数据渲染，不额外调API"""
        try:
            ltv_raw = pos_data.get("ltv", "0")
            ltv_val = float(ltv_raw) * 100 if ltv_raw else 0
            self._current_ltv = ltv_val
            total_collateral = float(pos_data.get("totalCollateral", "0"))
            total_debt = float(pos_data.get("totalDebt", "0"))
            self._total_collateral = total_collateral
            self._total_debt = total_debt
            self._collateral_val.config(text="{:,.2f} USDT".format(total_collateral))
            self._debt_val.config(text="{:,.2f} USDT".format(total_debt))
            import math
            self._fund_usdt = math.floor(fund_usdt_in * 100) / 100.0
            # 可释放 = 抵押品价值 - 负债/目标LTV
            target_ratio = self._config.borrow_target_ltv / 100.0
            min_collateral = total_debt / target_ratio if target_ratio > 0 else total_debt
            self._releasable = max(0, total_collateral - min_collateral)
            self._balance_val.config(text="{:,.2f} USDT".format(self._fund_usdt))
        except Exception as e:
            self._ltv_val.config(text="加载失败")

    def _set_pct(self, pct):
        if self._tab == "add":
            amount = self._fund_usdt * pct / 100.0
        else:
            amount = self._releasable * pct / 100.0
        self._amount_var.set("{:.2f}".format(amount))

    def _on_amount_change(self, *args):
        try:
            amt = float(self._amount_var.get())
        except ValueError:
            self._collateral_change.config(text="--")
            self._est_ltv.config(text="--")
            return
        if amt <= 0:
            self._collateral_change.config(text="--")
            self._est_ltv.config(text="--")
            return
        if self._tab == "add":
            new_collateral = self._total_collateral + amt
            change_text = "+{:,.2f} USDT".format(amt)
            change_color = "#10b981"
        else:
            new_collateral = self._total_collateral - amt
            change_text = "-{:,.2f} USDT".format(amt)
            change_color = "#ef4444"
        if new_collateral <= 0:
            self._collateral_change.config(text="抵押品不足", foreground="#ef4444")
            self._est_ltv.config(text="--")
            return
        new_ltv = (self._total_debt / new_collateral) * 100
        self._collateral_change.config(text=change_text, foreground=change_color)
        self._est_ltv.config(text="{:.2f}%".format(new_ltv))
        if new_ltv >= 85:
            self._est_ltv.config(foreground="#ef4444")
        elif new_ltv >= 75:
            self._est_ltv.config(foreground="#d97706")
        else:
            self._est_ltv.config(foreground="#10b981")

    def _on_confirm(self):
        amt_str = self._amount_var.get().strip()
        if not amt_str:
            messagebox.showwarning("提示", "请输入金额", parent=self)
            return
        try:
            amt = float(amt_str)
            if amt <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("提示", "请输入有效金额", parent=self)
            return
        direction = "0" if self._tab == "add" else "1"
        action = "追加" if self._tab == "add" else "减少"
        msg = "确认{0}抵押品 {1:.2f} USDT？".format(action, amt)
        if not _confirm_dialog(self, "确认操作", msg):
            return
        try:
            adjust_id = self._service.adjust_collateral("USDT", str(amt), direction)
            if hasattr(self._main_window, "_debug_log"):
                self._main_window._debug_log(f"{action}抵押品成功: {amt:.2f} USDT (adjustId={adjust_id})")
            if self._on_success:
                self._on_success()
                # 3秒后二次刷新，确保余额接口已更新
                self.after(3000, self._on_success)
            self.destroy()
        except Exception as e:
            if hasattr(self._main_window, "_debug_log"):
                self._main_window._debug_log(f"{action}抵押品失败: {str(e)[:100]}")
            messagebox.showerror("失败", "{0}抵押品失败: {1}".format(action, str(e)[:100]), parent=self)


class DebugLogWindow(tk.Toplevel):
    """调试日志窗口"""

    def __init__(self, parent, logs):
        super().__init__(parent)
        self.title("调试日志")
        self.geometry("700x450")
        self.transient(parent)
        self._build(logs)
        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        ww = self.winfo_width()
        wh = self.winfo_height()
        self.geometry(f"+{px + (pw - ww) // 2}+{py + (ph - wh) // 2}")

    def _build(self, logs):
        frame = ttk.Frame(self, padding=5)
        frame.pack(fill=tk.BOTH, expand=True)
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(toolbar, text=f"最近 {len(logs)} 条日志",
                  font=("", 9, "bold")).pack(side=tk.LEFT)
        copy_btn = ttk.Button(toolbar, text="复制全部",
                              command=self._copy_all)
        copy_btn.pack(side=tk.RIGHT)
        text_frame = ttk.Frame(frame)
        text_frame.pack(fill=tk.BOTH, expand=True)
        self._text = tk.Text(text_frame, wrap=tk.WORD, font=("Consolas", 9),
                             bg="#1e1e1e", fg="#d4d4d4")
        scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self._text.yview)
        self._text.configure(yscrollcommand=scroll.set)
        self._text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        for line in logs:
            self._text.insert(tk.END, line + "\n")
        self._text.configure(state=tk.DISABLED)

    def _copy_all(self):
        self._text.configure(state=tk.NORMAL)
        c = self._text.get("1.0", tk.END)
        self._text.configure(state=tk.DISABLED)
        self.clipboard_clear()
        self.clipboard_append(c)


class MainWindow:
    """主窗口 — 简洁版"""

    LEFT_WIDTH = 240

    def __init__(self):
        self._config_manager = ConfigManager()
        self._config = self._config_manager.load()
        self._service: Optional[StakingService] = None
        self._client: Optional[BybitClient] = None
        self._notifier: Optional[Notifier] = None
        self._init_client()

        self._root = tk.Tk()
        self._root.title("Bybit 质押借币")
        self._root.geometry("900x650")
        self._root.minsize(900, 590)

        # 单实例检测：如果已有实例运行，激活它并退出
        import ctypes as _ct
        _mutex = _ct.windll.kernel32.CreateMutexW(None, False, "BybitStakingApp_SingleInstance")
        if _ct.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            prev = _ct.windll.user32.FindWindowW(None, "Bybit 质押借币")
            if prev:
                _ct.windll.user32.ShowWindow(prev, 9)  # SW_RESTORE
                _ct.windll.user32.SetForegroundWindow(prev)
            self._root.destroy()
            import sys as _sys
            _sys.exit(0)

        self._root.update_idletasks()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        ww, wh = 900, 590
        self._root.geometry(f"{ww}x{wh}+{(sw - ww) // 2}+{(sh - wh) // 2}")

        self._protect_service = None
        self._debug_logs = deque(maxlen=200)  # 环形日志缓冲区
        self._BORROW_ERROR_MAP = {
            148012: "抵押品(USDT)余额不足",
            148011: "借币池余额不足",
            148002: "借币数量不合规",
            148005: "超出小数精度",
            10001: "参数错误",
        }

        self._build_ui()
        self._root.after(300, self._auto_init)
        # 系统托盘
        self._tray_added = False
        self._tray_hwnd = None
        self._orig_wndproc = None
        self._root.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)
        self._last_quota_warned = False
        self._rate_limit_strikes = 0  # ①档限流连续次数（全局）
        self._rl_dlg_open = False  # 限流弹窗是否已打开
        self._root.after(1000, self._check_minimize)  # 轮询检测最小化  # ??????
        self._download_url = None  # 新版本下载地址        self._root.after(1000, self._ban_check_timer)
        self._root.after(15000, self._ltv_alert_timer)  # LTV 飞书提醒
        self._root.after(2000, self._ltv_display_timer)  # LTV 屏幕刷新（2秒起步）
        self._root.after(5000, self._check_update)  # 首次检查，之后每30分钟

    def _debug_log(self, msg: str):
        """写入调试日志到环形缓冲区"""
        ts = datetime.now().strftime("%m-%d %H:%M:%S")
        self._debug_logs.append(f"[{ts}] {msg}")

    def _init_client(self):
        if self._config.api_key and self._config.api_secret:
            self._client = BybitClient(self._config)
            self._service = StakingService(self._client)
            self._notifier = Notifier(self._config.notify)
            self._protect_service = ProtectService(self._client, self._config.protect, self._notifier, log_func=self._debug_log)

    def _reinit_client(self):
        self._config = self._config_manager.get_config()
        self._init_client()
        self._update_network_label()
        self._auto_init()

    # ==================== 构建 UI ====================

    def _build_ui(self):
        main = ttk.Frame(self._root)
        main.pack(fill=tk.BOTH, expand=True)

        self._left = ttk.Frame(main, width=self.LEFT_WIDTH, relief=tk.GROOVE, borderwidth=1)
        self._left.pack(side=tk.LEFT, fill=tk.Y)
        self._left.pack_propagate(False)

        self._build_left_panel()

        ttk.Separator(main, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)

        self._right = ttk.Frame(main, padding=10)
        self._right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_right_panel()

        # 底部状态栏 — 三列：状态消息 | VPN | --
        status_bar = ttk.Frame(self._root, relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self._status_var = tk.StringVar(value="就绪")
        ttk.Label(status_bar, textvariable=self._status_var, anchor=tk.W, padding=(5, 2)).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        # 更新按钮（初始隐藏）
        self._update_btn = ttk.Button(status_bar, text="有新版本", command=self._open_update_url)
        self._update_btn.pack(side=tk.RIGHT, padx=5)
        self._update_btn.pack_forget()  # 默认隐藏

        # VPN 状态放在状态栏右侧
        ttk.Separator(status_bar, orient=tk.VERTICAL).pack(side=tk.RIGHT, fill=tk.Y)
        self._vpn_bar_var = tk.StringVar(value="VPN 未测试")
        ttk.Label(status_bar, textvariable=self._vpn_bar_var, anchor=tk.E, padding=(5, 2)).pack(
            side=tk.RIGHT
        )

    def _build_left_panel(self):
        pad = {"padx": 8, "pady": 3}
        f = self._left

        # 网络
        tk.Label(f, text="⬤ 网络", font=("", 9, "bold"), fg="#3b82f6").pack(anchor=tk.W, **pad)
        self._network_var = tk.StringVar(value=self._network_label())
        ttk.Label(f, textvariable=self._network_var, foreground="#2563eb").pack(anchor=tk.W, padx=16)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, **pad)

        # 总资产
        tk.Label(f, text="⬤ 总资产", font=("", 9, "bold"), fg="#10b981").pack(anchor=tk.W, **pad)
        self._total_var = tk.StringVar(value="$ --")
        ttk.Label(f, textvariable=self._total_var, foreground="#059669", font=("", 10, "bold")).pack(
            anchor=tk.W, padx=16
        )
        tk.Label(f, text="统一账户", font=("", 8), fg="#6b7280").pack(anchor=tk.W, padx=20)
        self._unified_var = tk.StringVar(value="可用 --  其他 --")
        ttk.Label(f, textvariable=self._unified_var, font=("", 8)).pack(anchor=tk.W, padx=28)
        self._fund_var = tk.StringVar(value="资金账户  --")
        ttk.Label(f, textvariable=self._fund_var, font=("", 8)).pack(anchor=tk.W, padx=20)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, **pad)

        # 持仓 LTV
        tk.Label(f, text="⬤ 持仓 LTV", font=("", 9, "bold"), fg="#f59e0b").pack(anchor=tk.W, **pad)
        self._ltv_var = tk.StringVar(value="--")
        self._last_pos_data = {}
        _ltv_row = ttk.Frame(f)
        _ltv_row.pack(anchor=tk.W, padx=16, fill=tk.X)
        ttk.Label(_ltv_row, textvariable=self._ltv_var, foreground="#d97706", font=("", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(_ltv_row, text="调整", width=4, command=self._open_adjust_collateral).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, **pad)

        # API 限额
        tk.Label(f, text="⬤ API 限额", font=("", 9, "bold"), fg="#8b5cf6").pack(anchor=tk.W, **pad)
        self._api_used_var = tk.StringVar(value="--/--")
        ttk.Label(f, textvariable=self._api_used_var).pack(anchor=tk.W, padx=16)
        self._api_remain_var = tk.StringVar(value="剩余: --")
        ttk.Label(f, textvariable=self._api_remain_var, font=("", 8)).pack(anchor=tk.W, padx=16)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, **pad)

        # 设置
        # 版本号（可点击查看更新日志）
        ver_label = ttk.Label(f, text=f"v{VERSION}", foreground="#3b82f6", font=("", 8, "underline"), cursor="hand2")
        ver_label.pack(pady=(10, 0))
        ver_label.bind("<Button-1>", lambda e: self._show_changelog())
        ver_label.bind("<Control-Button-1>", lambda e: self._show_debug_log())
        ttk.Button(f, text="检查更新", width=8, command=self._check_update).pack()
        ttk.Button(f, text="设置", command=self._open_settings).pack(pady=(10, 0))

    def _build_right_panel(self):
        pad = {"pady": 5}
        f = self._right

        # 发起借币
        form = ttk.LabelFrame(f, text="发起借币", padding=5)
        form.pack(fill=tk.X, **pad)

        # 抵押品信息行
        r0 = ttk.Frame(form)
        r0.pack(fill=tk.X, pady=0)
        ttk.Label(r0, text="抵押品:", width=10).pack(side=tk.LEFT)
        ttk.Label(r0, text="USDT（自动）", foreground="#059669").pack(side=tk.LEFT, padx=5)

        # 表头
        header = ttk.Frame(form)
        header.pack(fill=tk.X, pady=(3, 1))
        ttk.Label(header, text="", width=4).pack(side=tk.LEFT)  # 删除按钮占位
        ttk.Label(header, text="#", width=3, font=("", 8, "bold")).pack(side=tk.LEFT)
        ttk.Label(header, text="借入币种", width=10, font=("", 8, "bold")).pack(side=tk.LEFT, padx=(2, 0))
        ttk.Label(header, text="数量", width=10, font=("", 8, "bold")).pack(side=tk.LEFT, padx=(2, 0))
        ttk.Label(header, text="最大可借", width=22, font=("", 8, "bold")).pack(side=tk.LEFT, padx=(2, 0))
        ttk.Label(header, text="操作", width=16, font=("", 8, "bold")).pack(side=tk.LEFT, padx=(2, 0))

        # 币种行容器
        self._coin_rows = []
        self._row_container = ttk.Frame(form)
        self._row_container.pack(fill=tk.X)

        # 添加行按钮
        add_row = ttk.Frame(form)
        add_row.pack(fill=tk.X, pady=(0, 0))
        self._add_btn = ttk.Button(add_row, text="+ 添加币种", command=self._add_coin_row)
        self._add_btn.pack(side=tk.LEFT)

        # LTV 纠错参数（原齿轮按钮）
        btn_row = ttk.Frame(form)
        btn_row.pack(pady=(0, 0))
        self._ltv_correct_btn = ttk.Button(btn_row, text="⚙ 借币设置", command=self._open_borrow_settings)
        self._ltv_correct_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._ack_btn = tk.Button(btn_row, text="已借到", fg="white", bg="#dc2626",
                                   font=("", 9, "bold"), command=self._on_ack_borrow)

        # 初始添加 1 行
        self._add_coin_row()

        # 借贷记录（缩小高度）
        hist = ttk.LabelFrame(f, text="借贷记录", padding=10)
        hist.pack(fill=tk.BOTH, expand=True, **pad)

        columns = ("时间", "方向", "币种", "数量", "原因")
        self._history_tree = ttk.Treeview(hist, columns=columns, show="headings", height=5)
        self._history_tree.heading("时间", text="时间")
        self._history_tree.heading("方向", text="方向")
        self._history_tree.heading("币种", text="币种")
        self._history_tree.heading("数量", text="数量")
        self._history_tree.heading("原因", text="原因")
        self._history_tree.column("时间", width=120, anchor=tk.CENTER)
        self._history_tree.column("方向", width=55, anchor=tk.CENTER)
        self._history_tree.column("币种", width=60, anchor=tk.CENTER)
        self._history_tree.column("数量", width=80, anchor=tk.CENTER)
        self._history_tree.column("原因", width=180, anchor=tk.W)
        self._history_tree.pack(fill=tk.BOTH, expand=True)

        # 快捷操作
        actions = ttk.LabelFrame(f, text="快捷操作", padding=8)
        actions.pack(fill=tk.X, **pad)

        ttk.Button(actions, text="当前持仓", command=self._open_positions).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="账内划转", command=self._open_transfer).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="闪兑", command=self._open_exchange).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="借贷记录", command=self._show_borrow_log).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="测试连接", command=self._test_connection).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="全部刷新", command=self._refresh_all).pack(side=tk.RIGHT, padx=3)

    def _add_coin_row(self):
        """动态添加一个借币行（最多 5 行）"""
        if len(self._coin_rows) >= 5:
            return
        idx = len(self._coin_rows)
        row_frame = ttk.Frame(self._row_container)
        row_frame.pack(fill=tk.X, pady=1)

        row = CoinRow(index=idx)
        row.frame = row_frame

        # 删除按钮（最左侧，借币中禁用）
        del_btn = ttk.Button(row_frame, text="-", width=2,
                              command=lambda r=row: self._remove_coin_row(r))
        del_btn.pack(side=tk.LEFT, padx=(0, 4))

        # # 序号
        ttk.Label(row_frame, text=str(idx + 1), width=3, font=("", 9)).pack(side=tk.LEFT)

        # 币种
        row.coin_var = tk.StringVar()
        coin_entry = ttk.Entry(row_frame, textvariable=row.coin_var, width=10)
        coin_entry.pack(side=tk.LEFT, padx=(2, 0))
        # 手动点「计算」触发，不自动计算

        # 数量
        row.amount_var = tk.StringVar()
        amt_entry = ttk.Entry(row_frame, textvariable=row.amount_var, width=10)
        amt_entry.pack(side=tk.LEFT, padx=(2, 0))

        # 最大可借
        row.calc_var = tk.StringVar(value="--")
        row.calc_label = ttk.Label(row_frame, textvariable=row.calc_var,
                                    font=("", 9), foreground="#d97706", width=22, anchor=tk.W)
        row.calc_label.pack(side=tk.LEFT, padx=(2, 0))

        # 操作按钮
        btn_frame = ttk.Frame(row_frame)
        btn_frame.pack(side=tk.LEFT, padx=(2, 0))
        row.calc_btn = ttk.Button(btn_frame, text="计算", width=4,
                                   command=lambda r=row: self._manual_calc(r))
        row.calc_btn.pack(side=tk.LEFT, padx=(0, 2))
        row.borrow_btn = ttk.Button(btn_frame, text="借币" + str(idx + 1),
                                     command=lambda r=row: self._do_borrow(r))
        row.borrow_btn.pack(side=tk.LEFT)

        self._coin_rows.append(row)

        # 满 5 行隐藏添加按钮
        if len(self._coin_rows) >= 5:
            self._add_btn.pack_forget()
        else:
            self._add_btn.pack(side=tk.LEFT)

    def _remove_coin_row(self, row):
        """删除指定借币行并重新编号"""
        if len(self._coin_rows) <= 1:
            return  # 至少保留 1 行
        if row.looping:
            return  # 借币中禁止删除
        # 从 UI 移除
        row.frame.destroy()
        # 从列表移除
        self._coin_rows.remove(row)
        # 重新编号
        for i, r in enumerate(self._coin_rows):
            r.index = i
            if r.looping:
                r.borrow_btn.config(text=f"停止{i + 1}")
            else:
                r.borrow_btn.config(text=f"借币{i + 1}")
            # 更新序号标签
            for child in r.frame.winfo_children():
                if isinstance(child, ttk.Label):
                    try:
                        txt = child.cget("text")
                        if txt.isdigit():
                            child.config(text=str(i + 1))
                            break
                    except Exception:
                        pass
        # 不足 5 行显示添加按钮
        if len(self._coin_rows) < 5:
            self._add_btn.pack(side=tk.LEFT)

    def _find_row_by_index(self, index):
        """根据索引查找行"""
        for r in self._coin_rows:
            if r.index == index:
                return r
        return None

    def _has_any_looping(self):
        """是否有任何行正在循环借币"""
        return any(r.looping for r in self._coin_rows)


    # ==================== 左侧面板更新 ====================

    def _network_label(self) -> str:
        return "主网" if self._config.network == "mainnet" else "测试网"

    def _update_network_label(self):
        self._network_var.set(self._network_label())

    def _update_balances(self):
        """更新统一账户 + 资金账户余额（拆分 USDT / 其他）"""
        if not self._service:
            return
        try:
            # 统一账户总额 + USDT
            unified_total = self._service.get_unified_total_usd()
            unified_usdt = 0.0
            for ub in self._service.get_unified_balance():
                if ub.coin == "USDT":
                    unified_usdt = float(ub.usd_value) if ub.usd_value else 0.0
                    break
            unified_other = unified_total - unified_usdt
            # 资金账户 USDT
            fund_usdt = 0.0
            for fb in self._service.get_fund_balance():
                if fb.coin == "USDT":
                    fund_usdt = float(fb.usd_value) if fb.usd_value else 0.0
                    break
            total = unified_total + fund_usdt
            self._root.after(0, lambda: self._total_var.set(_fmt_usd(total)))
            self._root.after(0, lambda: self._unified_var.set(f"可用 {_fmt_usd(unified_usdt)}  其他 {_fmt_usd(unified_other)}"))
            self._root.after(0, lambda: self._fund_var.set(f"资金账户  {_fmt_usd(fund_usdt)}"))
            # 刷新持仓 LTV
            ltv = self._service.get_current_ltv()
            self._root.after(0, lambda: self._ltv_var.set(ltv))
            try:
                self._last_pos_data = self._service.get_position()
            except Exception:
                pass
            # 缓存持仓数据供调整窗口等复用
            try:
                self._last_pos_data = self._service.get_position()
            except Exception:
                pass
        except BybitApiError as e:
            self._root.after(0, lambda e=e: self._set_status(f'余额查询失败: {e}'))
        except Exception as e:
            self._root.after(0, lambda e=e: self._set_status(f'余额异常: {e}'))

    def _update_vpn_status(self, status: VpnStatus):
        icons = {"green": "[OK]", "yellow": "[WARN]", "red": "[ERR]"}
        icon = icons.get(status.level, "[?]")
        if status.connected:
            self._vpn_bar_var.set(f"VPN {icon} {status.latency_ms}ms")
        else:
            self._vpn_bar_var.set("VPN [ERR] 断连")

    def _update_rate_limit(self, rl: ApiRateLimit):
        if rl.banned:
            self._api_used_var.set("已封禁!")
            self._api_remain_var.set("等待解封...")
        elif rl.remaining == 0 and rl.limit > 0:
            self._api_used_var.set(f"{rl.used}/{rl.limit} 已用完!")
            self._api_remain_var.set("剩余: 0 暂停请求")
        else:
            self._api_used_var.set(f"{rl.used}/{rl.limit}" if rl.limit > 0 else "--/--")
            self._api_remain_var.set(f"剩余: {rl.remaining}" if rl.limit > 0 else "剩余: --")

    def _get_current_rate_limit(self) -> ApiRateLimit:
        if self._client:
            return self._client.rate_limit
        return ApiRateLimit()

    # ==================== 弹窗 ====================

    def _open_settings(self):
        SettingsDialog(self._root, self._config_manager, self._reinit_client)

    def _open_adjust_collateral(self):
        """打开调整抵押品弹窗（复用首页position缓存）"""
        if not self._service:
            messagebox.showwarning("提示", "请先配置 API 密钥")
            return
        try:
            pos = self._service.get_position()
            balances = self._service.get_fund_balance()
            fund_usdt = 0.0
            for b in balances:
                if b.coin == "USDT":
                    fund_usdt = float(b.wallet_balance)
                    break
            AdjustCollateralDialog(self._root, self._service, self._config_manager, pos, fund_usdt, self._refresh_all, self, self._ltv_var)
        except Exception as e:
            messagebox.showerror("错误", "获取数据失败: {0}".format(str(e)[:80]))

    def _open_protect(self):
        self._open_borrow_settings()

    def _open_positions(self):
        PositionsWindow(self._root, self._service, log_func=self._debug_log)

    def _open_transfer(self):
        TransferDialog(self._root, self._service, on_success=self._refresh_all, log_func=self._debug_log)

    def _open_exchange(self):
        if not self._client:
            messagebox.showwarning("提示", "请先配置 API 密钥")
            return
        exchange_svc = ExchangeService(self._client)
        ExchangeWindow(self._root, exchange_svc)

    def _show_borrow_log(self):
        """显示借贷成功记录（弹窗+日期筛选）"""
        import os as _os
        log_path = _os.path.join(_os.path.expanduser("~"), ".bybit_staking", "borrow_success.log")
        today = datetime.now()
        wk_ago = today - timedelta(days=6)

        win = tk.Toplevel(self._root)
        win.title("借贷成功记录")
        win.geometry("600x420")
        try:
            _center_window(win, self._root)
        except Exception:
            pass

        # ---- 日期筛选栏 ----
        bar = ttk.Frame(win)
        bar.pack(fill=tk.X, padx=5, pady=(5, 0))
        ttk.Label(bar, text="起始").pack(side=tk.LEFT)
        start_var = tk.StringVar(value=wk_ago.strftime("%Y-%m-%d"))
        ttk.Entry(bar, textvariable=start_var, width=12).pack(side=tk.LEFT, padx=3)
        ttk.Label(bar, text="结束").pack(side=tk.LEFT, padx=(10, 0))
        end_var = tk.StringVar(value=today.strftime("%Y-%m-%d"))
        ttk.Entry(bar, textvariable=end_var, width=12).pack(side=tk.LEFT, padx=3)
        ttk.Label(bar, text="  格式: YYYY-MM-DD").pack(side=tk.LEFT)

        # ---- 表格 ----
        tree = ttk.Treeview(win, columns=("time", "coin", "amount", "order"), show="headings", height=15)
        tree.heading("time", text="时间")
        tree.heading("coin", text="币种")
        tree.heading("amount", text="数量")
        tree.heading("order", text="订单号")
        tree.column("time", width=160)
        tree.column("coin", width=60, anchor=tk.CENTER)
        tree.column("amount", width=90, anchor=tk.CENTER)
        tree.column("order", width=260)

        scrollbar = ttk.Scrollbar(win, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)

        def _do_query():
            tree.delete(*tree.get_children())
            try:
                sd = datetime.strptime(start_var.get().strip(), "%Y-%m-%d")
                ed = datetime.strptime(end_var.get().strip(), "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            except Exception:
                return
            if not _os.path.exists(log_path):
                return
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except Exception:
                            continue
                        raw = entry.get("time", "")
                        try:
                            t = datetime.strptime(raw[:10], "%Y-%m-%d")
                        except Exception:
                            continue
                        if sd <= t <= ed:
                            tree.insert("", 0, values=(
                                entry.get("time", ""),
                                entry.get("coin", ""),
                                entry.get("amount", ""),
                                entry.get("order_id", ""),
                            ))
            except Exception:
                pass

        ttk.Button(bar, text="查询", command=_do_query).pack(side=tk.LEFT, padx=5)
        _do_query()

    # ==================== 操作 ====================

    def _test_connection(self):
        self._set_status("正在测试连接...")
        self._run_async(self._do_test_connection)

    def _do_test_connection(self):
        vpn = VpnStatus()
        if self._client:
            vpn = self._client.test_latency()
        self._root.after(0, lambda: self._update_vpn_status(vpn))

        api_ok = False
        if self._service:
            try:
                self._service.get_account_info()
                api_ok = True
            except BybitApiError:
                pass

        rl = self._get_current_rate_limit()
        self._root.after(0, lambda: self._update_rate_limit(rl))

        # 余额
        if self._service:
            self._run_async(self._update_balances)

        if vpn.connected and api_ok:
            self._root.after(0, lambda: self._set_status("连接正常"))
        elif vpn.connected:
            self._root.after(0, lambda: self._set_status("VPN通但API不通（检查密钥）"))
        else:
            self._root.after(0, lambda: self._set_status("无法连接"))

    def _refresh_all(self):
        self._set_status("正在刷新...")
        self._run_async(self._do_refresh_all)

    def _do_refresh_all(self):
        if self._client:
            vpn = self._client.test_latency()
            self._root.after(0, lambda: self._update_vpn_status(vpn))

        if not self._service:
            self._root.after(0, lambda: self._set_status("请先配置 API 密钥"))
            return

        # 余额
        self._run_async(self._update_balances)

        # 借贷记录
        try:
            borrow_history = self._service.get_borrow_history(limit=30)
            repay_history = self._service.get_repay_history(limit=30)
            combined = []
            for h in borrow_history:
                combined.append({
                    "time": h.get("createdTime", ""),
                    "direction": "借入",
                    "coin": h.get("loanCoin", ""),
                    "amount": h.get("loanAmount", "0"),
                })
            for h in repay_history:
                combined.append({
                    "time": h.get("createdTime", ""),
                    "direction": "还款",
                    "coin": h.get("coin", ""),
                    "amount": h.get("repayAmount", "0"),
                })
            combined.sort(key=lambda x: x["time"], reverse=True)
            combined = combined[:30]
            self._root.after(0, lambda: self._update_history(combined))
        except BybitApiError as e:
            self._root.after(0, lambda: self._set_status(f"记录刷新失败: {e}"))

        rl = self._get_current_rate_limit()
        self._root.after(0, lambda: self._update_rate_limit(rl))

        self._root.after(0, lambda: self._set_status("刷新完成"))

    def _update_history(self, items):
        for row in self._history_tree.get_children():
            self._history_tree.delete(row)
        for item in items:
            self._history_tree.insert("", tk.END, values=(
                item["time"], item["direction"], item["coin"], item["amount"], item.get("reason", ""),
            ))

    def _do_calc_collateral(self, row, loan_amt):
        self._do_auto_calc(row, row.coin_var.get().strip().upper(), loan_amt)


    def _manual_calc(self, row):
        """手动点击某行「计算」按钮"""
        if not self._service:
            return
        coin = row.coin_var.get().strip().upper()
        if not coin:
            return
        self._set_status("正在计算...")
        row.amount_var.set("")
        self._run_async(lambda r=row, c=coin: self._auto_fill_max(r, c))

    def _auto_calc(self, row):
        """币种输入变化时自动触发计算"""
        if not self._service:
            return
        if row.auto_filling:
            return
        if row.calc_after_id:
            self._root.after_cancel(row.calc_after_id)
        coin = row.coin_var.get().strip().upper()
        amt = row.amount_var.get().strip()
        if not coin:
            return
        # 币种变了 -> 清空数量，重新自动填入
        if row.last_coin and row.last_coin != coin:
            row.auto_filling = True
            row.amount_var.set("")
            row.auto_filling = False
            amt = ""
        row.last_coin = coin
        if not amt:
            row.calc_after_id = self._root.after(300, lambda r=row, c=coin: self._run_async(lambda: self._auto_fill_max(r, c)))
        else:
            row.calc_after_id = self._root.after(300, lambda r=row, c=coin, a=amt: self._run_async(lambda: self._do_auto_calc(r, c, a)))

    def _auto_fill_max(self, row, loan_coin):
        """自动计算最大可借并填入数量栏"""
        try:
            # 币种已变，丢弃旧结果
            cur = row.coin_var.get().strip().upper()
            if cur != loan_coin:
                return
            info = self._service.calculate_max_borrow(loan_coin, self._config.borrow_target_ltv / 100.0)
            # 币种不可借
            if not info.get("coin_borrowable", True):
                lab = "该币种不可借"
                self._root.after(0, lambda r=row, l=lab: r.calc_var.set(l))
                self._root.after(0, lambda r=row: r.calc_label.config(foreground="#ef4444"))
                return
            if info["can_borrow"] and float(info["max_amount"]) > 0:
                max_amt = info["max_amount"]
                real_max = str(int(float(max_amt)))
                safe_amt = str(int(float(max_amt)))
                lab = f"最大 {real_max} | LTV " + info["current_ltv"]
                self._root.after(0, lambda r=row, l=lab: r.calc_var.set(l))
                self._root.after(0, lambda r=row: r.calc_label.config(foreground="#10b981"))
                self._root.after(0, lambda r=row, s=safe_amt, c=loan_coin: self._fill_amount(r, s, c))
            else:
                # 诊断：显示具体原因
                detail = ""
                if float(info.get("total_collateral", "0")) <= 0:
                    detail = "资金账户USDT为0"
                elif float(info.get("available_usdt", "0")) <= 0 and float(info.get("max_amount_usd", "0")) <= 0:
                    detail = "可借额度为0(余额×80%≤0)"
                elif float(info.get("max_amount_usd", "0")) <= 0:
                    detail = "可借USD为0"
                else:
                    detail = "币价获取失败或为0"
                self._root.after(0, lambda r=row, d=detail: r.calc_var.set(f"LTV已满: {d} | " + info["current_ltv"]))
                self._root.after(0, lambda r=row: r.calc_label.config(foreground="#d97706"))
        except Exception:
            self._root.after(0, lambda r=row: r.calc_var.set("计算失败"))
            self._root.after(0, lambda r=row: self._set_borrow_enabled(r, False))

    def _fill_amount(self, row, amt, loan_coin):
        """填入数量，保留最大可借显示"""
        row.auto_filling = True
        row.amount_var.set(amt)
        row.auto_filling = False
        self._root.after(0, lambda r=row: self._set_borrow_enabled(r, True))

    def _do_auto_calc(self, row, loan_coin, loan_amt):
        try:
            cur = row.coin_var.get().strip().upper()
            if cur != loan_coin:
                return
            want = float(loan_amt)
            if want <= 0:
                return
            info = self._service.calculate_max_borrow(loan_coin, self._config.borrow_target_ltv / 100.0)
            cur_ltv = info["current_ltv"]
            max_amt = info["max_amount"]
            if not info["can_borrow"]:
                lab = "无法借币  |  LTV " + cur_ltv
                self._root.after(0, lambda r=row, l=lab: r.calc_var.set(l))
                self._root.after(0, lambda r=row: r.calc_label.config(foreground="#ef4444"))
                return
            if want > float(max_amt):
                lab = f"超限  |  最大{max_amt}  |  LTV {cur_ltv}"
                self._root.after(0, lambda r=row, l=lab: r.calc_var.set(l))
                self._root.after(0, lambda r=row: r.calc_label.config(foreground="#ef4444"))
            else:
                lab = f"可借 {loan_amt}  |  LTV {cur_ltv}"
                collateral_usd = (want * self._service.get_coin_price(loan_coin)) / 0.80
                if collateral_usd > 0:
                    lab += f"  |  需抵押 {collateral_usd:.0f} USDT"
                self._root.after(0, lambda r=row, l=lab: r.calc_var.set(l))
                self._root.after(0, lambda r=row: r.calc_label.config(foreground="#10b981"))
        except Exception:
            self._root.after(0, lambda r=row: r.calc_var.set("计算异常"))

    def _set_borrow_enabled(self, row, enabled):
        """控制某行借币按钮状态"""
        if enabled:
            row.borrow_btn.config(state="normal")
        else:
            row.borrow_btn.config(state="disabled")

    def _set_controls_enabled(self, enabled):
        """封禁时禁用/启用所有借币控件"""
        state = "normal" if enabled else "disabled"
        for row in self._coin_rows:
            row.borrow_btn.config(state=state)

    def _stop_all_loops(self):
        """停止所有借币行循环（限流触发时调用，线程安全）"""
        for r in self._coin_rows:
            if r.looping:
                r.looping = False
            self._root.after(0, lambda r=r: r.borrow_btn.config(text=f"借币{r.index + 1}"))

    def _handle_rate_limit_tier(self, e: BybitApiError) -> bool:
        """三档限流检测：命中后停止全部借币+弹窗+飞书，返回True表示已处理"""
        msg = e.message.upper()
        if e.code == 403:
            self._rate_limit_strikes = 0
            self._trigger_rate_limit_tier(
                3, "IP 已被 Bybit 封禁（HTTP 403）", "请更换 IP / 重启 VPN",
                ban_seconds=1800, show_countdown=False,
            )
            return True
        if e.code == 429:
            self._rate_limit_strikes = 0
            self._trigger_rate_limit_tier(
                2, "IP 访问超限（HTTP 429）", "请降低借币速率或暂停借币",
                ban_seconds=360, show_countdown=True,
            )
            return True
        if e.code == 10006 or "TOO_MANY_VISITS" in msg or "RATE_LIMIT" in msg:
            self._rate_limit_strikes += 1
            if self._rate_limit_strikes >= 3:
                self._rate_limit_strikes = 0
                self._trigger_rate_limit_tier(
                    1, "连续3次接口限流（10006）",
                    "请降低借币速率（当前 {0:.1f} 秒）".format(self._config.borrow_rate),
                    ban_seconds=0, show_countdown=False,
                )
                return True
            return False
        # 其他错误重置①档计数（保持"连续"语义）
        self._rate_limit_strikes = 0
        return False

    def _trigger_rate_limit_tier(self, tier, cause, advice, ban_seconds=0, show_countdown=False):
        """触发限流档位：停止所有借币 + 弹窗 + 飞书"""
        until = time.time() + ban_seconds if ban_seconds > 0 else 0
        self._stop_all_loops()
        now = time.strftime("%m-%d %H:%M:%S")
        self._root.after(0, lambda n=now, t=tier, c=cause: self._log_local(n, "限流⛔", "-", "-", f"已触发{t}档限流: {c}"))
        self._root.after(0, lambda t=tier: self._set_status(f"⛔ 已触发{t}档限流，停止所有借币"))
        self._root.after(0, lambda: self._show_rate_limit_dialog(tier, cause, advice, until, show_countdown))
        if self._notifier:
            self._notifier.send(
                f"限流提醒（第{tier}档）",
                f"已触发{tier}档限流\n原因: {cause}\n状态: 已停止所有借币\n建议: {advice}\n时间: {now}",
                platform="all",
            )

    def _show_rate_limit_dialog(self, tier, cause, advice, until=0, show_countdown=False):
        """限流提醒弹窗（居中模态，②档带实时倒计时）"""
        if self._rl_dlg_open:
            return
        self._rl_dlg_open = True
        cfg = {
            1: ("⚠️", "#d97706", "已触发①档限流"),
            2: ("🚫", "#dc2626", "已触发②档限流"),
            3: ("⛔", "#7f1d1d", "已触发③档限流"),
        }
        icon, header_bg, header_text = cfg[tier]

        def on_close():
            self._rl_dlg_open = False
            dlg.destroy()

        dlg = tk.Toplevel(self._root)
        dlg.title("限流提醒")
        dlg.resizable(False, False)
        dlg.transient(self._root)
        dlg.grab_set()
        dlg.configure(bg="white")
        dlg.protocol("WM_DELETE_WINDOW", on_close)

        header = tk.Frame(dlg, bg=header_bg, height=64)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text=icon, font=("", 22), bg=header_bg, fg="white").pack(side=tk.LEFT, padx=(18, 10), pady=12)
        tk.Label(header, text=header_text, font=("", 14, "bold"), bg=header_bg, fg="white").pack(side=tk.LEFT, pady=12)

        body = tk.Frame(dlg, bg="white")
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)
        card = tk.Frame(body, bg="#f9fafb", highlightbackground="#e5e7eb", highlightthickness=1)
        card.pack(fill=tk.X)

        info_rows = [
            ("触发原因", cause),
            ("当前状态", "已停止所有借币"),
            ("处理建议", advice),
        ]
        labels = {}
        if tier == 2:
            info_rows.append(("禁用倒计时", "⏳ 计算中"))
            info_rows.append(("解除时间", "6分钟后自动恢复"))
        elif tier == 3:
            info_rows.append(("禁用时长", "30分钟"))
        info_rows.append(("飞书通知", "已发送"))

        for label, value in info_rows:
            row = tk.Frame(card, bg="#f9fafb")
            row.pack(fill=tk.X, padx=14, pady=6)
            tk.Label(row, text=label, font=("", 10), bg="#f9fafb", fg="#6b7280", width=10, anchor="w").pack(side=tk.LEFT)
            val_lbl = tk.Label(row, text=value, font=("", 10, "bold"), bg="#f9fafb", fg="#374151", anchor="w")
            val_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            labels[label] = val_lbl

        btn_row = tk.Frame(dlg, bg="white")
        btn_row.pack(pady=(0, 14))

        def on_extra():
            on_close()
            self._open_borrow_settings()

        if tier == 1:
            tk.Button(btn_row, text="知道了", font=("", 10),
                      bg="#e5e7eb", fg="#374151", relief="flat", padx=16, pady=4,
                      command=on_close).pack(side=tk.LEFT, padx=(0, 8))
            tk.Button(btn_row, text="去调整速率", font=("", 10, "bold"),
                      bg="#3b82f6", fg="white", relief="flat", padx=16, pady=4,
                      command=on_extra).pack(side=tk.LEFT)
        else:
            tk.Button(btn_row, text="知道了", font=("", 10, "bold"),
                      bg="#3b82f6", fg="white", relief="flat", padx=16, pady=4,
                      command=on_close).pack(side=tk.LEFT)

        # ②档实时倒计时
        if tier == 2 and until > 0:
            def tick():
                try:
                    remaining = int(until - time.time())
                    if remaining <= 0:
                        labels["禁用倒计时"].config(text="⏳ 已解除")
                        return
                    mins, secs = divmod(remaining, 60)
                    labels["禁用倒计时"].config(text=f"⏳ {mins}分{secs}秒")
                    dlg.after(1000, tick)
                except tk.TclError:
                    pass
            tick()

        _center_window(dlg, self._root)

    def _open_borrow_settings(self):
        """打开借币设置"""
        BorrowSettingsDialog(self._root, self._config_manager, self._reinit_client)

    def _start_borrow_silent(self, row):
        """纠错后静默发起借币（不弹确认框）"""
        if not self._service:
            return
        coin = row.coin_var.get().strip().upper()
        amt = row.amount_var.get().strip()
        if not coin or not amt:
            return
        try:
            info = self._service.calculate_max_borrow(coin, self._config.borrow_target_ltv / 100.0)
            want = float(amt)
            if info["can_borrow"] and want > float(info["max_amount"]):
                self._set_status(f"⚠ 借币{row.index+1}纠错后仍超LTV限制，放弃发起")
                return
            price = self._service.get_coin_price(coin)
            if price <= 0:
                self._set_status(f"⚠ 借币{row.index+1}无法获取币价")
                return
            need_collateral = (want * price) / (self._config.borrow_target_ltv / 100.0)
            col_amt = f"{need_collateral:.2f}"
        except Exception as e:
            self._set_status(f"⚠ 借币{row.index+1}静默发起异常: {e}")
            return
        # 直接启动循环（跳过确认弹窗）
        row.looping = True
        row.fail_count = 0
        row.borrow_btn.config(text=f"停止{row.index + 1}")
        self._set_status(f"借币{row.index+1} 循环中...")
        if not hasattr(self, "_scheduler_running") or not self._scheduler_running:
            self._scheduler_running = True
            self._run_async(lambda r=row, c=col_amt, lc=coin: self._scheduler_loop(r, lc, c))

    def _do_borrow(self, row):
        """启动/停止某行的循环借币"""
        if row.looping:
            # 停止
            row.looping = False
            row.borrow_btn.config(text=f"借币{row.index + 1}")
            self._set_status(f"已停止借币{row.index + 1}")
            return
        if not self._service:
            messagebox.showwarning("提示", "请先配置 API 密钥")
            return
        coin = row.coin_var.get().strip().upper()
        amt = row.amount_var.get().strip()
        if not coin or not amt:
            messagebox.showwarning("提示", f"借币{row.index + 1}: 请填写币种和数量")
            return
        try:
            info = self._service.calculate_max_borrow(coin, self._config.borrow_target_ltv / 100.0)
            want = float(amt)
            if info["can_borrow"] and want > float(info["max_amount"]):
                msg = "当前LTV " + info["current_ltv"] + "\n最大可借 " + info["max_amount"] + " " + coin
                messagebox.showwarning("超出LTV限制", msg)
                return
            price = self._service.get_coin_price(coin)
            if price <= 0:
                messagebox.showwarning("错误", "无法获取币价")
                return
            need_collateral = (want * price) / (self._config.borrow_target_ltv / 100.0)
            col_amt = f"{need_collateral:.2f}"
        except Exception as e:
            messagebox.showwarning("计算失败", f"LTV检查异常: {e}")
            return
        msg = f"借入 {amt} {coin}\n抵押 {col_amt} USDT\n\n确认发起循环借币？"
        if not _confirm_dialog(self._root, "循环借币", msg):
            return
        row.looping = True
        row.fail_count = 0
        row.borrow_btn.config(text=f"停止{row.index + 1}")
        self._set_status(f"借币{row.index + 1} 循环中...")
        # 调度器只启动一次（全局唯一）
        if not hasattr(self, "_scheduler_running") or not self._scheduler_running:
            self._scheduler_running = True
            self._run_async(lambda r=row, c=col_amt, lc=coin: self._scheduler_loop(r, lc, c))
            # scheduler_running 在 scheduler_loop 结束时重置

    def _scheduler_loop(self, init_row, loan_coin, col_amt):
        """排队交替借币调度器：遍历所有活跃行，每人借一次"""
        import random, time as _time
        # 先借第一笔
        self._borrow_once(init_row, loan_coin, col_amt)
        base_rate = self._config_manager.get_config().borrow_rate
        delay = base_rate + random.uniform(0.01, 0.15)
        _time.sleep(delay)
        # 轮询所有活跃行
        while self._has_any_looping():
            for row in list(self._coin_rows):
                if not row.looping:
                    continue
                if not self._has_any_looping():
                    break
                coin = row.coin_var.get().strip().upper()
                amt = row.amount_var.get().strip()
                if not coin or not amt:
                    continue
                # 每次重新计算抵押品（其他币借走后额度会变）
                try:
                    price = self._service.get_coin_price(coin)
                    if price <= 0:
                        continue
                    need_collateral = (float(amt) * price) / (self._config.borrow_target_ltv / 100.0)
                    col = f"{need_collateral:.2f}"
                except Exception:
                    continue
                self._borrow_once(row, coin, col)
                base_rate = self._config_manager.get_config().borrow_rate
                delay = base_rate + random.uniform(0.01, 0.15)
                _time.sleep(delay)
        self._scheduler_running = False

    def _borrow_once(self, row, loan_coin, col_amt):
        """单次借币请求（一行一次）"""
        import time as _time
        if not row.looping:
            return
        loan_amt = row.amount_var.get().strip()
        if not loan_amt:
            return
        attempt = row.fail_count + 1
        now = _time.strftime("%m-%d %H:%M:%S")
        ERROR_MAP = {
            148012: "抵押品(USDT)余额不足",
            148011: "借币池余额不足",
            148002: "借币数量不合规",
            148005: "超出小数精度限制",
            10001: "请求参数错误",
        }
        ERROR_TEXT = {
            "LTV_EXCEEDS_THRESHOLD": "超过最大LTV限制",
            "COLLATERAL_BALANCE_NOT_ENOUGH": "抵押品余额不足",
            "LOAN_FINANCE_BALANCE_NOT_ENO": "借币池余额不足",
            "LOAN_PLATFORM_QUOTA_NOT": "平台借币配额不足",
            "LOAN_PLATFORM_QUOTA_NOT_ENO": "平台借币配额不足",
            "LOAN_QUANTITY_NOT_ALLOWED": "借币数量不合规",
            "LOAN_AMOUNT_EXCEED_MAX": "超出最大可借数量",
            "LOAN_AMOUNT_EXCEED_LIMIT": "超出最大可借数量",
            "REPAY_AMOUNT_EXCEED_DEBT": "还款额超过欠款",
            "INSUFFICIENT_BALANCE_IN_S": "账户余额不足",
            "INSUFFICIENT_BALANCE": "账户余额不足",
            "PARAMETER_ERROR": "请求参数错误",
            "REQUEST_PARAMETER_ERROR": "请求参数错误",
            "TOO_MANY_VISITS": "请求过于频繁，限流",
            "RATE_LIMIT": "请求过于频繁，限流",
            "ORDER_NOT_FOUND": "订单不存在",
            "COLLATERAL_NOT_ENOUGH": "抵押品不足",
        }
        try:
            col_coin = "USDT"
            order_id = self._service.borrow(col_coin, loan_coin, col_amt, loan_amt)
            self._rate_limit_strikes = 0  # 借币成功重置①档限流计数
            # 成功
            self._root.after(0, lambda n=now, lc=loan_coin, la=loan_amt:
                self._log_local(n, "借入\u2705", lc, la, "成功"))
            row.looping = False
            self._root.after(0, lambda r=row: r.borrow_btn.config(text=f"借币{r.index + 1}"))
            self._root.after(0, lambda oid=order_id, r=row, cc=col_coin, ca=col_amt, lc=loan_coin, la=loan_amt:
                self._show_borrow_success(r, oid, cc, ca, lc, la))
            return
        except BybitApiError as e:
            reason = ERROR_MAP.get(e.code)
            if not reason:
                msg_upper = e.message.upper()
                for key, val in ERROR_TEXT.items():
                    if key.upper() in msg_upper:
                        reason = val
                        break
                if not reason:
                    reason = e.message[:60]
            # 三档限流检测（全局：命中后停止所有借币并弹窗）
            if self._handle_rate_limit_tier(e):
                return
            if e.code == 148012 or "LTV" in e.message.upper() or "THRESHOLD" in e.message.upper() or "COLLATERAL" in e.message.upper():
                row.fail_count += 1
            else:
                row.fail_count = 0
            # LTV 自动纠错检查（该行独立）
            ltv_cfg = self._config_manager.get_config().ltv_correct
            if ltv_cfg.enabled and row.fail_count >= ltv_cfg.trigger_count:
                row.looping = False
                self._root.after(0, lambda r=row: r.borrow_btn.config(text=f"借币{r.index + 1}"))
                self._root.after(0, lambda c=row.fail_count, w=ltv_cfg.wait_seconds, ri=row.index:
                    self._set_status(f"\u26a0 借币{ri+1} LTV超限{c}次，{w}秒后自动重算..."))
                self._root.after(0, lambda n=now, lc=loan_coin, la=loan_amt, ri=row.index:
                    self._log_local(n, "超限停止", lc, la, f"借币{ri+1}触发纠错"))
                _time.sleep(ltv_cfg.wait_seconds)
                self._root.after(0, lambda r=row: self._do_auto_recalc(r, ltv_cfg.redundancy_ratio, ltv_cfg.auto_restart))
                return
            # 失败日志
            self._root.after(0, lambda n=now, lc=loan_coin, la=loan_amt, rsn=reason, ri=row.index:
                self._log_local(n, f"借入\u274c", lc, la, f"借币{ri+1}: {rsn}"))
            self._root.after(0, lambda ri=row.index, rsn=reason:
                self._set_status(f"\u274c 借币{ri+1} 失败: {rsn}"))
            # 配额连续失败计数（独立于LTV纠错）
            if "配额" in reason:
                row.quota_fail_count += 1
                if row.quota_fail_count >= 3:
                    row.quota_fail_count = 0
                    if self._notifier and self._config.notify.quota_feishu_enabled:
                        self._notifier.send(
                            "配额不足提醒",
                            f"借币{row.index+1}\n币种: {loan_coin}\n数量: {loan_amt}\n原因: {reason}\n已连续3次配额不足，继续重试中",
                            platform="all"
                        )
            else:
                row.quota_fail_count = 0
            # 连续失败飞书提醒
            if row.fail_count >= 3 and row.fail_count % 3 == 0:
                if self._notifier:
                    self._notifier.send(
                        "LTV超限警告",
                        f"借币{row.index+1}\n币种: {loan_coin}\n数量: {loan_amt}\n原因: {reason}\n连续失败: {row.fail_count}次",
                        platform="all"
                    )
        except Exception as e:
            err_msg = str(e)[:80]
            self._root.after(0, lambda n=now, lc=loan_coin, la=loan_amt, ri=row.index, em=err_msg:
                self._log_local(n, "借入\u274c", lc, la, f"借币{ri+1}: {em}"))
            self._root.after(0, lambda ri=row.index, em=err_msg:
                self._set_status(f"\u274c 借币{ri+1}: {em}"))

    def _do_auto_recalc(self, row, redundancy_ratio, auto_restart):
        """LTV 自动纠错：重算某行并可选自动发起"""
        try:
            coin = row.coin_var.get().strip().upper()
            if not coin:
                self._set_status(f"\u26a0 纠错: 借币{row.index+1}未输入币种")
                return
            target_ltv = self._config.borrow_target_ltv / 100.0
            info = self._service.calculate_max_borrow(coin, target_ltv)
            if not info["can_borrow"] or float(info["max_amount"]) <= 0:
                self._set_status(f"\u26a0 纠错: 借币{row.index+1}不可借或可借为0")
                return
            safe_str = str(int(float(info["max_amount"])))
            self._root.after(0, lambda r=row, s=safe_str: r.amount_var.set(s))
            self._root.after(0, lambda r=row, ml=info["max_amount"], sr=safe_str:
                r.calc_var.set(f"已纠错: 最大{ml} -> 填入{sr}"))
            self._root.after(0, lambda ri=row.index, sr=safe_str:
                self._set_status(f"\u2705 借币{ri+1}纠错: 填入{sr}"))
            if auto_restart:
                self._root.after(500, lambda r=row: self._start_borrow_silent(r))
        except Exception as e:
            self._root.after(0, lambda ri=row.index, err=str(e):
                self._set_status(f"\u26a0 借币{ri+1}纠错异常: {err}"))
    def _show_borrow_success(self, row, order_id, col_coin, col_amt, loan_coin, loan_amt):
        """借币成功：停止所有其他行 + 显示红色按钮 + 飞书通知"""
        # 停止所有其他行
        for r in self._coin_rows:
            if r is not row and r.looping:
                r.looping = False
                self._root.after(0, lambda r=r: r.borrow_btn.config(text=f"借币{r.index + 1}"))
        row.ack_data = (order_id, col_coin, col_amt, loan_coin, loan_amt)
        row.notifying = True
        # 显示红色已借到按钮
        self._ack_btn.pack(side=tk.LEFT, padx=5)
        self._color_blink()
        self._set_status(f"借币{row.index+1}成功！已停止其他借币")
        # 飞书循环通知
        threading.Thread(target=self._notify_loop_row,
                         args=(row, order_id, col_coin, col_amt, loan_coin, loan_amt),
                         daemon=True).start()
        self._run_async(self._refresh_ltv)
        self._refresh_all()

        # 隐蔽日志上报（飞书多维表格 + 本地 JSON）
        log_borrow_success(loan_coin, loan_amt, self._config.borrow_rate, order_id)

    def _notify_loop_row(self, row, order_id, col_coin, col_amt, loan_coin, loan_amt):
        """该行成功后的飞书循环通知"""
        import time as _time
        while row.notifying:
            if self._notifier:
                self._notifier.send_stake_success(order_id, col_coin, col_amt, loan_coin, loan_amt)
            _time.sleep(5)

    def _on_ack_borrow(self):
        """点击已借到：停止所有通知 + 隐藏按钮"""
        for row in self._coin_rows:
            row.notifying = False
        self._ack_btn.pack_forget()
        self._set_status("借币完成")
        self._refresh_all()

    def _do_borrow_async(self, col_coin, loan_coin, col_amt, loan_amt):
        """单次借币（保留兼容，旧接口）"""
        try:
            order_id = self._service.borrow(col_coin, loan_coin, col_amt, loan_amt)
            self._root.after(0, lambda: messagebox.showinfo("借币成功", f"订单号: {order_id}"))
            self._root.after(0, lambda: self._set_status(f"借币成功: {order_id}"))
            if self._notifier:
                self._notifier.send_stake_success(order_id, col_coin, col_amt, loan_coin, loan_amt)
            self._root.after(0, self._refresh_all)
        except BybitApiError as e:
            self._root.after(0, lambda: messagebox.showerror("借币失败", str(e)))
            self._root.after(0, lambda: self._set_status("借币失败"))

    def _log_local(self, time_str, direction, coin, amount, reason=""):
        """本地写入借贷记录表格"""
        self._history_tree.insert("", 0, values=(time_str, direction, coin, amount, reason))
        # 保留最近20条
        children = self._history_tree.get_children()
        if len(children) > 20:
            for child in children[20:]:
                self._history_tree.delete(child)

    def _color_blink(self):
        """按钮颜色闪烁一次"""
        self._ack_btn.config(bg="#ef4444")
        self._root.after(500, lambda: self._ack_btn.config(bg="#dc2626"))

    # ==================== 工具方法 ====================

    def _set_status(self, text: str):
        self._status_var.set(text)

    def _run_async(self, func):
        def safe_run():
            try:
                func()
            except Exception as e:
                import traceback
                self._root.after(0, lambda e=e: self._set_status(f"线程异常: {e}"))
                traceback.print_exc()
        threading.Thread(target=safe_run, daemon=True).start()

    def _auto_init(self):
        """启动后自动：测试连接 + 刷新余额 + 启动托盘"""
        self._run_async(self._do_auto_init)
        self._init_tray()

    def _do_auto_init(self):
        # 测 VPN
        vpn = VpnStatus()
        if self._client:
            vpn = self._client.test_latency()
            self._root.after(0, lambda: self._update_vpn_status(vpn))

        if not self._service:
            self._root.after(0, lambda: self._set_status("请先配置 API 密钥"))
            return

        # 余额
        self._run_async(self._update_balances)

        # API 连通性
        api_ok = False
        try:
            self._service.get_account_info()
            api_ok = True
        except BybitApiError:
            pass

        rl = self._get_current_rate_limit()
        self._root.after(0, lambda: self._update_rate_limit(rl))

        if api_ok:
            self._root.after(0, lambda: self._set_status("连接正常"))
        elif vpn.connected:
            self._root.after(0, lambda: self._set_status("VPN通但API不通（检查密钥）"))
        else:
            self._root.after(0, lambda: self._set_status("无法连接"))

    def _ban_check_timer(self):
        """每5秒检查 API 封禁状态"""
        self._check_ban_status()
        self._root.after(1000, self._ban_check_timer)

    def _check_ban_status(self):
        """检查并更新封禁状态"""
        if self._client:
            rl = self._client.rate_limit
            # 实时更新 API 限额标签
            self._root.after(0, lambda: self._update_rate_limit(rl))
            if rl.limit == 0:
                return
            if rl.banned:
                self._set_controls_enabled(False)
                remaining = int(rl.banned_until - __import__("time").time())
                if remaining > 0:
                    mins = remaining // 60
                    secs = remaining % 60
                    self._set_status(f"已封禁，约 {mins}分{secs}秒 后解封")
            elif rl.remaining == 0 and rl.limit > 0:
                # ????????????????????????
                if not self._last_quota_warned:
                    self._set_status("API ????????????")
                    self._last_quota_warned = True
            else:
                self._set_controls_enabled(True)
                if self._last_quota_warned:
                    self._last_quota_warned = False
                    self._set_status("")  # ???????

    def _refresh_ltv(self):
        """刷新 LTV 并触发保护检查"""
        try:
            ltv = self._service.get_current_ltv()
            self._root.after(0, lambda: self._ltv_var.set(ltv))
            # 缓存持仓数据供调整窗口等复用
            try:
                self._last_pos_data = self._service.get_position()
            except Exception:
                pass
            # 自动保护检查
            self._run_async(lambda l=ltv: self._check_protect(l))
        except Exception:
            pass
    def _check_protect(self, ltv_str):
        """自动保护：LTV 超标时划转并追加抵押"""
        if not self._protect_service:
            return
        try:
            result = self._protect_service.checkAndProtect(ltv_str)
            if result:
                self._root.after(0, lambda r=result: self._set_status(f"保护: {r}"))
                print(f"[保护] 结果: {result}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._root.after(0, lambda e=e: self._set_status(f"保护异常: {e}"))

    def _ltv_display_timer(self):
        """LTV 定时刷新：每2秒"""
        self._run_async(self._refresh_ltv)
        self._root.after(2000, self._ltv_display_timer)


    def _check_update(self):
        """后台检查更新 + 每30分钟重试"""
        self._run_async(self._do_check_update_wrapper)
        # 30分钟后重试
        self._root.after(30 * 60 * 1000, self._check_update)

    def _do_check_update_wrapper(self):
        import urllib.request, json as _json
        update_url = self._config.update_url or UPDATE_URL
        if not update_url:
            return
        try:
            req = urllib.request.Request(update_url)
            proxy = self._config.proxy
            if proxy.enabled and proxy.http:
                req.set_proxy(proxy.http, "http")
                req.set_proxy(proxy.http, "https")
            req.add_header("Accept", "application/vnd.github+json")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            remote_ver = data.get("tag_name", "").lstrip("v").split("_")[0]
            tag_name = data.get("tag_name", "")
            if remote_ver and remote_ver != VERSION:
                dl_url = get_download_url(tag_name)
                self._download_url = dl_url
                self._root.after(0, lambda: self._update_btn.pack(side=tk.RIGHT, padx=5))
                self._root.after(0, lambda: self._update_btn.config(text=f"v{remote_ver} 可用"))
        except Exception:
            pass

    def _show_debug_log(self):
        """打开调试日志窗口"""
        DebugLogWindow(self._root, list(self._debug_logs))

    def _show_changelog(self):
        """显示更新日志弹窗"""
        win = tk.Toplevel(self._root)
        win.title("更新日志")
        win.resizable(False, False)
        win.transient(self._root)
        win.grab_set()

        f = ttk.Frame(win, padding=15)
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(f, text="更新日志", font=("", 12, "bold")).pack(anchor=tk.W)

        canvas = tk.Canvas(f, width=420, height=300, highlightthickness=0)
        scrollbar = ttk.Scrollbar(f, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=(10, 0))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=(10, 0))

        for ver, items in CHANGELOG.items():
            ttk.Label(scroll_frame, text=f"v{ver}", font=("", 10, "bold"), foreground="#3b82f6").pack(anchor=tk.W, pady=(8, 2))
            for item in items:
                ttk.Label(scroll_frame, text=f"  • {item}", font=("", 9), wraplength=380).pack(anchor=tk.W, pady=1)

        ttk.Button(f, text="关闭", command=win.destroy).pack(pady=(10, 0))
        _center_window(win, self._root)

    def _open_update_url(self):
        """下载新版本并自动替换"""
        if not self._download_url:
            import webbrowser
            webbrowser.open(RELEASES_URL)
            return
        self._set_status("正在下载更新...")
        self._run_async(self._do_download_update)

    def _do_download_update(self):
        import urllib.request, os, sys, subprocess
        try:
            dl_url = self._download_url
            if getattr(sys, "frozen", False):
                current_exe = sys.executable
            else:
                current_exe = os.path.abspath(__file__)
            exe_dir = os.path.dirname(current_exe)
            # 使用实际 EXE 文件名而非写死名称
            if current_exe.endswith(".exe"):
                old_exe = current_exe
                base_name = os.path.splitext(os.path.basename(current_exe))[0]
                new_exe = os.path.join(exe_dir, base_name + "_new.exe")
            else:
                old_exe = os.path.join(exe_dir, "BybitStaking.exe")
                new_exe = os.path.join(exe_dir, "BybitStaking_new.exe")

            self._root.after(0, lambda: self._set_status("下载中..."))
            req = urllib.request.Request(dl_url)
            proxy = self._config.proxy
            if proxy.enabled and proxy.http:
                req.set_proxy(proxy.http, "http")
                req.set_proxy(proxy.http, "https")
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(new_exe, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = int(downloaded * 100 / total)
                            self._root.after(0, lambda p=pct: self._set_status(f"下载中 {p}%"))

            self._root.after(0, lambda: self._set_status("下载完成，正在安装..."))
            updater = os.path.join(exe_dir, "_updater.bat")
            q = chr(34)
            # 杀掉所有旧进程（包括可能残留的同名进程）
            exe_name = os.path.basename(old_exe)
            bat = (
                "@echo off\n"
                "chcp 65001 >nul\n"
                "echo Waiting for app to close...\n"
                "timeout /t 2 /nobreak >nul\n"
                f"taskkill /f /im {q}{exe_name}{q} 2>nul\n"
                f"taskkill /f /pid {os.getpid()} 2>nul\n"
                "timeout /t 2 /nobreak >nul\n"
                "set RETRY=0\n"
                ":retry\n"
                f"move /y {q}{new_exe}{q} {q}{old_exe}{q} 2>nul\n"
                f"if errorlevel 1 (\n"
                "    echo Retry move...\n"
                "    set /a RETRY+=1\n"
                "    if %RETRY% LSS 15 (\n"
                "        timeout /t 2 /nobreak >nul\n"
                "        goto retry\n"
                "    )\n"
                ")\n"
                f"echo Starting {exe_name}...\n"
                f"start {q}{q} {q}{old_exe}{q}\n"
                "echo Update done\n"
                f"del {q}%~f0{q} 2>nul"
            )
            with open(updater, "w", encoding="utf-8") as f:
                f.write(bat)
            subprocess.Popen(["cmd", "/c", updater], creationflags=0x00000008)
            self._root.after(500, self._root.destroy)
        except Exception as e:
            self._root.after(0, lambda e=e: self._set_status(f"Update failed: {e}"))

        # ====== 系统托盘 ======
    def _init_tray(self):
        """启动时创建托盘图标并持续运行"""
        if hasattr(self, '_tray_icon') and self._tray_icon is not None:
            return
        import pystray
        from PIL import Image, ImageDraw
        import threading

        # 创建图标
        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([6, 6, 58, 58], fill=(59, 130, 246))
        draw.text((20, 18), 'B', fill=(255, 255, 255))

        self._tray_icon = pystray.Icon(
            'bybit_staking',
            img,
            'Bybit 质押借币',
            menu=pystray.Menu(
                pystray.MenuItem('显示主窗口', self._tray_show, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('退出', self._tray_exit),
            ),
        )
        # 后台线程持续运行
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _tray_show(self, icon=None, item=None):
        """从托盘恢复主窗口"""
        self._root.after(0, self._restore_from_tray)

    def _tray_exit(self, icon=None, item=None):
        """退出应用"""
        self._root.after(0, self._root.destroy)

    def _minimize_to_tray(self):
        """最小化/关闭 → 隐藏到托盘（托盘一直在运行）"""
        self._root.withdraw()

    def _restore_from_tray(self):
        """从托盘恢复窗口"""
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def _check_minimize(self):
        """轮询检测最小化状态"""
        try:
            if self._root.state() == "iconic":
                self._minimize_to_tray()
        except Exception:
            pass
        self._root.after(500, self._check_minimize)

    def run(self):
        try:
            self._root.mainloop()
        finally:
            try:
                if hasattr(self, '_tray_icon') and self._tray_icon:
                    self._tray_icon.stop()
            except Exception:
                pass
    def _ltv_alert_timer(self):
        self._check_ltv_alert()
        interval = self._config.notify.ltv_alert_interval * 1000
        self._root.after(interval, self._ltv_alert_timer)

    def _check_ltv_alert(self):
        if not self._service or not self._notifier:
            return
        threshold = self._config.notify.ltv_threshold
        if threshold <= 0:
            return
        try:
            ltv_str = self._service.get_current_ltv()
            if ltv_str == "--":
                return
            ltv_val = float(ltv_str.rstrip("%"))
            if ltv_val > threshold:
                msg = f"LTV \u8b66\u544a\uff1a\u5f53\u524d LTV {ltv_str}\uff0c\u8d85\u8fc7\u8bbe\u5b9a\u9608\u503c {threshold}%"
                self._notifier.send("LTV \u8b66\u544a", msg, "feishu")
        except Exception:
            pass




