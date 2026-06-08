"""
桌面主界面 — 简洁版
左侧信息栏 + 右侧操作区 + 弹窗（设置、持仓、划转）
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from typing import Optional

from ..config.config_manager import ConfigManager, AppConfig
from ..api.bybit_client import BybitClient, BybitApiError, VpnStatus, ApiRateLimit
from ..business.staking_service import StakingService
from ..notify.notifier import Notifier


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


def _fmt_usd(value: float) -> str:
    """格式化 USD 金额"""
    if value >= 10000:
        return f"${value:,.0f}"
    elif value >= 1:
        return f"${value:,.2f}"
    else:
        return "$0.00"


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

        # 借币请求速率
        rate_frame = ttk.LabelFrame(self, text="借币请求速率", padding=10)
        rate_frame.pack(fill=tk.X, **pad)
        ttk.Label(rate_frame, text="选择请求间隔（实际会在此基础上加 0.01~0.5 秒随机浮动）:").pack(anchor=tk.W)
        self._rate_var = tk.StringVar(value=str(self._config.borrow_rate))
        rate_combo = ttk.Combobox(rate_frame, textvariable=self._rate_var,
            values=["0.5", "1.5", "2.5", "3.5", "4.5", "5.5"], width=10, state="readonly")
        rate_combo.pack(anchor=tk.W, pady=5)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, pady=(10, 5), padx=10)
        ttk.Button(btn_row, text="保存", command=self._save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_row, text="取消", command=self.destroy).pack(side=tk.RIGHT)

    def _save(self):
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
        self._config_manager.set_borrow_rate(float(self._rate_var.get()))
        self._config_manager.save()
        self._on_save()
        self.destroy()


class PositionsWindow(tk.Toplevel):
    """当前持仓弹窗 — 支持还币"""

    def __init__(self, parent, service: Optional[StakingService]):
        super().__init__(parent)
        self._service = service
        self.title("当前持仓")
        self.geometry("600x400")
        self.resizable(True, True)
        self.transient(parent)

        self._build()
        _center_window(self, parent)

        if self._service:
            self._refresh()

    def _build(self):
        pad = {"padx": 10, "pady": 5}

        columns = ("借入币种", "欠款总额", "利率(时)", "操作")
        self._tree = ttk.Treeview(self, columns=columns, show="headings", height=8)
        self._tree.heading("借入币种", text="借入币种")
        self._tree.heading("欠款总额", text="欠款总额")
        self._tree.heading("利率(时)", text="利率(时)")
        self._tree.heading("操作", text="操作")
        self._tree.column("借入币种", width=100, anchor=tk.CENTER)
        self._tree.column("欠款总额", width=130, anchor=tk.CENTER)
        self._tree.column("利率(时)", width=100, anchor=tk.CENTER)
        self._tree.column("操作", width=80, anchor=tk.CENTER)
        self._tree.pack(fill=tk.BOTH, expand=True, **pad)

        # 双击行也可还币
        self._tree.bind("<Double-1>", lambda e: self._repay_selected())

        self._summary_var = tk.StringVar(value="抵押品: --  |  总欠款: --  |  LTV: --")
        ttk.Label(self, textvariable=self._summary_var).pack(anchor=tk.W, **pad)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, **pad)
        ttk.Button(btn_row, text="一键还清全部", command=self._repay_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text="还币", command=self._repay_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text="刷新", command=self._refresh).pack(side=tk.RIGHT)

    def _refresh(self):
        if not self._service:
            return
        try:
            pos = self._service.get_position()
            for row in self._tree.get_children():
                self._tree.delete(row)

            bl = pos.get("borrowList", [])
            cl = pos.get("collateralList", [])
            total_debt = pos.get("totalDebt", "0")
            ltv_raw = pos.get("ltv", "")
            ltv = f"{float(ltv_raw)*100:.1f}%" if ltv_raw else "--"

            for b in bl:
                rate = b.get("flexibleHourlyInterestRate", "0")
                rate_pct = f"{float(rate)*100:.5f}%" if rate else "--"
                self._tree.insert("", tk.END, values=(
                    b.get("loanCurrency", ""),
                    b.get("flexibleTotalDebt", "0"),
                    rate_pct,
                    "[还币]",
                ))

            cols = ", ".join(f"{c.get('currency','')}: {c.get('amount','')}" for c in cl) or "--"
            self._summary_var.set(
                f"抵押品: {cols}  |  总欠款 USD: ${total_debt}  |  LTV: {ltv}"
            )
        except BybitApiError as e:
            messagebox.showerror("查询失败", str(e), parent=self)

    def _repay_selected(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一笔持仓", parent=self)
            return
        values = self._tree.item(sel[0])["values"]
        coin = values[0]
        debt = values[1]
        self._show_repay_dialog(coin, debt)

    def _show_repay_dialog(self, coin, max_amount):
        dlg = tk.Toplevel(self)
        dlg.title(f"还币 - {coin}")
        dlg.geometry("300x180")
        dlg.resizable(False, False)
        dlg.transient(self)

        # 使用原始欠款值，不做截断
        max_rounded = str(max_amount)




        ttk.Label(dlg, text=f"币种: {coin}\n欠款总额: {max_rounded}", padding=10).pack()

        row = ttk.Frame(dlg)
        row.pack(pady=5)
        ttk.Label(row, text="还款数量:").pack(side=tk.LEFT)
        amt_var = tk.StringVar(value=max_rounded)
        amt_entry = ttk.Entry(row, textvariable=amt_var, width=14)
        amt_entry.pack(side=tk.LEFT, padx=5)

        def do_repay(amount=None):
            amt = amount if amount else amt_var.get().strip()
            if not amt:
                return
            try:
                rid = self._service.repay_smart(coin, amt)
                messagebox.showinfo("还款成功", f"还款ID: {rid}", parent=dlg)
                dlg.destroy()
                self._refresh()
            except BybitApiError as e:
                messagebox.showerror("还款失败", str(e), parent=dlg)

        ttk.Button(row, text="确认还款", command=lambda: do_repay()).pack(side=tk.LEFT, padx=5)
        ttk.Button(dlg, text="一键还清", command=lambda: do_repay(max_rounded)).pack(pady=5)

        _center_window(dlg, self)

    def _repay_all(self):
        if not self._service:
            return
        pos = self._service.get_position()
        bl = pos.get("borrowList", [])
        if not bl:
            messagebox.showinfo("提示", "没有待还持仓", parent=self)
            return
        msg = "\n".join(f"{b['loanCurrency']}: {b['flexibleTotalDebt']}" for b in bl)
        if not messagebox.askyesno("一键还清全部", f"确认还清以下币种？\n\n{msg}", parent=self):
            return
        for b in bl:
            try:
                amt = str(b['flexibleTotalDebt'])
                self._service.repay_smart(b["loanCurrency"], amt)
            except BybitApiError as e:
                messagebox.showerror("还币失败", f"{b['loanCurrency']}: {e}", parent=self)
        self._refresh()


class TransferDialog(tk.Toplevel):
    """划转弹窗 — 统一账户 ↔ 资金账户"""

    def __init__(self, parent, service: Optional[StakingService], on_success=None):
        super().__init__(parent)
        self._service = service
        self._on_success = on_success
        self.title("账内划转 — 统一 ↔ 资金")
        self.resizable(False, False)
        self.transient(parent)

        self._build()
        _center_window(self, parent)

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
        ttk.Label(row1, text="数量:", width=6).pack(side=tk.LEFT)
        self._amount = ttk.Entry(row1, width=14)
        self._amount.pack(side=tk.LEFT)

        ttk.Button(self, text="执行划转", command=self._do_transfer).pack(pady=15)

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

        if not messagebox.askyesno("确认划转", label, parent=self):
            return
        try:
            tid = self._service.transfer(coin, amount, from_acc, to_acc)
            messagebox.showinfo("划转成功", f"划转ID: {tid}", parent=self)
            if self._on_success:
                self._on_success()
        except BybitApiError as e:
            messagebox.showerror("划转失败", str(e), parent=self)


class MainWindow:
    """主窗口 — 简洁版"""

    LEFT_WIDTH = 200

    def __init__(self):
        self._config_manager = ConfigManager()
        self._config = self._config_manager.load()
        self._service: Optional[StakingService] = None
        self._client: Optional[BybitClient] = None
        self._notifier: Optional[Notifier] = None
        self._init_client()

        self._root = tk.Tk()
        self._root.title("Bybit 质押借币")
        self._root.geometry("900x580")
        self._root.minsize(800, 520)

        self._root.update_idletasks()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        ww, wh = 900, 580
        self._root.geometry(f"{ww}x{wh}+{(sw - ww) // 2}+{(sh - wh) // 2}")

        self._borrow_looping = False
        self._BORROW_ERROR_MAP = {
            148012: "抵押品(USDT)余额不足",
            148011: "借币池余额不足",
            148002: "借币数量不合规",
            148005: "超出小数精度",
            10001: "参数错误",
        }

        self._build_ui()
        self._root.after(300, self._auto_init)
        self._root.after(1000, self._start_ltv_timer)

    def _init_client(self):
        if self._config.api_key and self._config.api_secret:
            self._client = BybitClient(self._config)
            self._service = StakingService(self._client)
            self._notifier = Notifier(self._config.notify)

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
        self._unified_var = tk.StringVar(value="统一: $ --")
        ttk.Label(f, textvariable=self._unified_var, font=("", 8)).pack(anchor=tk.W, padx=20)
        self._fund_var = tk.StringVar(value="资金: $ --")
        ttk.Label(f, textvariable=self._fund_var, font=("", 8)).pack(anchor=tk.W, padx=20)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, **pad)

        # 持仓 LTV
        tk.Label(f, text="⬤ 持仓 LTV", font=("", 9, "bold"), fg="#f59e0b").pack(anchor=tk.W, **pad)
        self._ltv_var = tk.StringVar(value="--")
        ttk.Label(f, textvariable=self._ltv_var, foreground="#d97706", font=("", 10, "bold")).pack(
            anchor=tk.W, padx=16
        )

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, **pad)

        # API 限额
        tk.Label(f, text="⬤ API 限额", font=("", 9, "bold"), fg="#8b5cf6").pack(anchor=tk.W, **pad)
        self._api_used_var = tk.StringVar(value="--/--")
        ttk.Label(f, textvariable=self._api_used_var).pack(anchor=tk.W, padx=16)
        self._api_remain_var = tk.StringVar(value="剩余: --")
        ttk.Label(f, textvariable=self._api_remain_var, font=("", 8)).pack(anchor=tk.W, padx=16)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, **pad)

        # 设置
        ttk.Button(f, text="设置", command=self._open_settings).pack(pady=10)

    def _build_right_panel(self):
        pad = {"pady": 5}
        f = self._right

        # 发起借币
        form = ttk.LabelFrame(f, text="发起借币", padding=10)
        form.pack(fill=tk.X, **pad)

        r1 = ttk.Frame(form)
        r1.pack(fill=tk.X, pady=2)
        self._collateral_coin = "USDT"  # 固定 USDT
        self._collateral_amount = ""    # 自动计算
        ttk.Label(r1, text="抵押品:", width=10).pack(side=tk.LEFT)
        ttk.Label(r1, text="USDT（自动）", foreground="#059669").pack(side=tk.LEFT, padx=5)
        self._calc_var = tk.StringVar(value="--")
        ttk.Label(r1, textvariable=self._calc_var, font=("", 10, "bold"), foreground="#d97706").pack(side=tk.LEFT, padx=5)
        # 计算按钮已移除

        r2 = ttk.Frame(form)
        r2.pack(fill=tk.X, pady=2)
        ttk.Label(r2, text="借入币种:", width=10).pack(side=tk.LEFT)
        self._loan_coin = ttk.Entry(r2, width=12)
        self._loan_coin.pack(side=tk.LEFT, padx=5)
        ttk.Label(r2, text="数量:", width=6).pack(side=tk.LEFT)
        self._loan_amount = ttk.Entry(r2, width=14)
        self._loan_amount.pack(side=tk.LEFT, padx=5)

        btn_row = ttk.Frame(form)
        btn_row.pack(pady=(8, 0))
        self._borrow_btn = ttk.Button(btn_row, text="发起借币", command=self._do_borrow)
        self._borrow_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._ack_btn = tk.Button(btn_row, text="已借到", fg="white", bg="#dc2626",
                                   font=("", 9, "bold"), command=self._on_ack_borrow)
        self._loan_amount.bind("<KeyRelease>", lambda e: self._root.after(300, self._auto_calc))
        self._loan_coin.bind("<KeyRelease>", lambda e: self._root.after(300, self._auto_calc))
        self._ltv_ok = False

        # 初始隐藏
        self._ack_data = None  # 存储借币成功数据

        # 借贷记录
        hist = ttk.LabelFrame(f, text="借贷记录", padding=10)
        hist.pack(fill=tk.BOTH, expand=True, **pad)

        columns = ("时间", "方向", "币种", "数量", "原因")
        self._history_tree = ttk.Treeview(hist, columns=columns, show="headings", height=8)
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
        ttk.Button(actions, text="查询利率", command=self._show_interest).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="测试连接", command=self._test_connection).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="全部刷新", command=self._refresh_all).pack(side=tk.RIGHT, padx=3)

    # ==================== 左侧面板更新 ====================

    def _network_label(self) -> str:
        return "主网" if self._config.network == "mainnet" else "测试网"

    def _update_network_label(self):
        self._network_var.set(self._network_label())

    def _update_balances(self):
        """更新统一账户 + 资金账户余额"""
        if not self._service:
            return
        try:
            unified = self._service.get_unified_total_usd()
            fund = self._service.get_fund_total_usd()
            total = unified + fund
            self._root.after(0, lambda: self._total_var.set(_fmt_usd(total)))
            self._root.after(0, lambda: self._unified_var.set(f"统一: {_fmt_usd(unified)}"))
            self._root.after(0, lambda: self._fund_var.set(f"资金: {_fmt_usd(fund)}"))
            # 刷新持仓 LTV
            ltv = self._service.get_current_ltv()
            self._root.after(0, lambda: self._ltv_var.set(ltv))
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
        self._api_used_var.set(f"{rl.used}/{rl.limit}" if rl.limit > 0 else "--/--")
        self._api_remain_var.set(f"剩余: {rl.remaining}" if rl.limit > 0 else "剩余: --")

    def _get_current_rate_limit(self) -> ApiRateLimit:
        if self._client:
            return self._client.rate_limit
        return ApiRateLimit()

    # ==================== 弹窗 ====================

    def _open_settings(self):
        SettingsDialog(self._root, self._config_manager, self._reinit_client)

    def _open_positions(self):
        PositionsWindow(self._root, self._service)

    def _open_transfer(self):
        TransferDialog(self._root, self._service, on_success=self._refresh_all)

    def _show_interest(self):
        if not self._service:
            messagebox.showwarning("提示", "请先配置 API 密钥")
            return
        self._set_status("正在查询利率...")
        self._run_async(self._do_show_interest)

    def _do_show_interest(self):
        try:
            rates = self._service.get_interest_rate()
            lines = []
            for r in rates:
                lines.append(f"{r.coin}:  日利率 {r.daily_rate}  |  年利率 {r.yearly_rate}")
            text = "\n".join(lines) if lines else "无数据"
            self._root.after(0, lambda: messagebox.showinfo("当前借贷利率", text))
            self._root.after(0, lambda: self._set_status("利率查询完成"))
        except BybitApiError as e:
            self._root.after(0, lambda: messagebox.showerror("查询失败", str(e)))

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

    def _calc_collateral(self):
        """自动计算所需抵押品"""
        if not self._service:
            return
        loan_coin = self._loan_coin.get().strip().upper()
        loan_amt = self._loan_amount.get().strip()
        if not loan_coin or not loan_amt:
            return
        self._run_async(lambda: self._do_calc_collateral(loan_coin, loan_amt))

    def _auto_calc(self):
        if not self._service:
            return
        if hasattr(self, "_auto_filling") and self._auto_filling:
            return
        if hasattr(self, "_calc_after_id") and self._calc_after_id:
            self._root.after_cancel(self._calc_after_id)
        loan_coin = self._loan_coin.get().strip().upper()
        loan_amt = self._loan_amount.get().strip()
        if not loan_coin:
            return
        # 币种变了 → 清空数量，重新自动填入
        if hasattr(self, "_last_coin") and self._last_coin and self._last_coin != loan_coin:
            self._auto_filling = True
            self._loan_amount.delete(0, "end")
            self._auto_filling = False
            loan_amt = ""
        self._last_coin = loan_coin
        if not loan_amt:
            self._calc_after_id = self._root.after(300, lambda: self._run_async(lambda: self._auto_fill_max(loan_coin)))
        else:
            self._calc_after_id = self._root.after(300, lambda: self._run_async(lambda: self._do_auto_calc(loan_coin, loan_amt)))

    def _auto_fill_max(self, loan_coin):
        """自动计算最大可借并填入数量栏"""
        try:
            info = self._service.calculate_max_borrow(loan_coin)
            if info["can_borrow"] and float(info["max_amount"]) > 0:
                max_amt = info["max_amount"]
                safe_amt = int(float(max_amt) * 0.85)
                int_amt = str(safe_amt)
                # 显示最大可借
                lab = f"最大可借 {int_amt} {loan_coin}  |  LTV " + info["current_ltv"]
                self._root.after(0, lambda l=lab: self._calc_var.set(l))
                self._root.after(0, lambda: self._calc_var.config(foreground="#10b981"))
                self._root.after(0, lambda: self._fill_amount(int_amt, loan_coin))
            else:
                self._root.after(0, lambda: self._calc_var.set("无法借币  |  LTV " + info["current_ltv"]))
                self._root.after(0, lambda: self._calc_var.config(foreground="#ef4444"))
                self._root.after(0, lambda: self._set_borrow_enabled(False))
        except Exception:
            self._root.after(0, lambda: self._calc_var.set("计算失败"))
            self._root.after(0, lambda: self._set_borrow_enabled(False))

    def _fill_amount(self, amt, loan_coin):
        """填入数量并触发 LTV 计算"""
        self._auto_filling = True
        self._loan_amount.delete(0, "end")
        self._loan_amount.insert(0, amt)
        self._auto_filling = False
        # 填入后自动触发 LTV 计算
        self._do_auto_calc(loan_coin, amt)

    def _do_auto_calc(self, loan_coin, loan_amt):
        try:
            want = float(loan_amt)
            if want <= 0:
                return
            info = self._service.calculate_max_borrow(loan_coin)
            cur_ltv = info["current_ltv"]
            max_amt = info["max_amount"]
            total_debt = float(info["total_debt"])
            total_collateral = float(info["total_collateral"])
            if not info["can_borrow"]:
                lab = "无法借币  |  LTV " + cur_ltv
                self._root.after(0, lambda l=lab: self._calc_var.set(l))
                self._root.after(0, lambda: self._calc_var.config(foreground="#ef4444"))
                self._root.after(0, lambda: self._set_borrow_enabled(False))
                return
            price = self._service.get_coin_price(loan_coin)
            if price <= 0:
                self._root.after(0, lambda: self._calc_var.set("无法获取币价"))
                self._root.after(0, lambda: self._set_borrow_enabled(False))
                return
            want_usd = want * price
            need_collateral = want_usd / 0.80
            projected_ltv = (total_debt + want_usd) / (total_collateral + need_collateral) * 100
            if want <= float(max_amt) and projected_ltv <= 80:
                lab = f"{need_collateral:.2f} USDT  |  LTV {cur_ltv} -> {projected_ltv:.1f}%"
                self._root.after(0, lambda l=lab: self._calc_var.set(l))
                self._root.after(0, lambda: self._calc_var.config(foreground="#10b981"))
                self._root.after(0, lambda: self._set_borrow_enabled(True))
            else:
                lab = "LTV超限!max" + max_amt + " " + loan_coin + "  |  " + cur_ltv
                self._root.after(0, lambda l=lab: self._calc_var.set(l))
                self._root.after(0, lambda: self._calc_var.config(foreground="#ef4444"))
                self._root.after(0, lambda: self._set_borrow_enabled(False))
        except Exception:
            self._root.after(0, lambda: self._calc_var.set("计算失败"))
            self._root.after(0, lambda: self._set_borrow_enabled(False))

    def _set_borrow_enabled(self, enabled: bool):
        self._ltv_ok = enabled
        if enabled:
            self._borrow_btn.config(state="normal")
        else:
            self._borrow_btn.config(state="disabled")

    def _do_calc_collateral(self, loan_coin, loan_amt):
        self._do_auto_calc(loan_coin, loan_amt)

    def _do_borrow(self):
        if self._borrow_looping:
            self._borrow_looping = False
            self._borrow_btn.config(text="发起借币")
            self._set_status("已停止循环借币")
            return
        if not self._service:
            messagebox.showwarning("提示", "请先配置 API 密钥")
            return
        col_coin = self._collateral_coin
        loan_coin = self._loan_coin.get().strip().upper()
        loan_amt = self._loan_amount.get().strip()
        if not loan_coin or not loan_amt:
            messagebox.showwarning("提示", "请填写借入币种和数量")
            return
        try:
            info = self._service.calculate_max_borrow(loan_coin)
            if not info["can_borrow"]:
                msg = "当前LTV " + info["current_ltv"] + "\n已无可用额度"
                messagebox.showwarning("无法借币", msg)
                return
            want = float(loan_amt)
            if want > float(info["max_amount"]):
                msg = "当前LTV " + info["current_ltv"] + "\n最大可借 " + info["max_amount"] + " " + loan_coin + "\n你输入 " + loan_amt + " " + loan_coin
                messagebox.showwarning("超出LTV限制", msg)
                return
            price = self._service.get_coin_price(loan_coin)
            if price <= 0:
                messagebox.showwarning("错误", "无法获取币价")
                return
            need_collateral = (want * price) / 0.80
            col_amt = f"{need_collateral:.2f}"
        except Exception as e:
            messagebox.showwarning("计算失败", f"LTV检查异常: {e}")
            return
        msg = "抵押 {} {}\n借入 {} {}\n\n将每2-3秒尝试一次，直到成功".format(
            col_amt, col_coin, loan_amt, loan_coin)
        if not messagebox.askyesno("循环借币", msg):
            return
        self._borrow_looping = True
        self._borrow_btn.config(text="停止循环")
        self._set_status("循环借币中...")
        self._run_async(lambda: self._loop_borrow(col_coin, loan_coin, col_amt, loan_amt))

    def _loop_borrow(self, col_coin, loan_coin, col_amt, loan_amt):
        """循环借币，2-3 秒随机间隔，直到成功或手动停止"""
        import random, time as _time
        ltv_fail_count = 0  # 连续 LTV 失败计数
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
            "LOAN_FINANCE_BALANCE_NOT_ENOUGH": "借币池余额不足",
            "LOAN_QUANTITY_NOT_ALLOWED": "借币数量不合规",
        }
        attempt = 0
        while self._borrow_looping:
            attempt += 1
            now = _time.strftime("%m-%d %H:%M:%S")
            try:
                order_id = self._service.borrow(col_coin, loan_coin, col_amt, loan_amt)
                # 成功
                self._root.after(0, lambda oid=order_id, n=now, lc=loan_coin, la=loan_amt:
                    self._log_local(n, "借入\u2705", lc, la, "成功"))
                self._borrow_looping = False
                self._root.after(0, lambda: self._borrow_btn.config(text="发起借币"))
                self._root.after(0, lambda oid=order_id, a=attempt, cc=col_coin, ca=col_amt, lc=loan_coin, la=loan_amt:
                    self._show_borrow_success(oid, a, cc, ca, lc, la))
                return
            except BybitApiError as e:
                reason = ERROR_MAP.get(e.code)
                if not reason:
                    reason = ERROR_TEXT.get(e.message[:30], e.message[:40])
                if e.code == 148012 or "LTV" in e.message.upper() or "THRESHOLD" in e.message.upper():
                    ltv_fail_count += 1
                else:
                    ltv_fail_count = 0
                self._root.after(0, lambda n=now, lc=loan_coin, la=loan_amt, r=reason:
                    self._log_local(n, "借入\u274c", lc, la, r))
                self._root.after(0, lambda a=attempt, r=reason:
                    self._set_status(f"\u274c 第{a}次失败: {r}"))
                # LTV 连续失败 3 次，推送飞书/钉钉提醒
                if ltv_fail_count >= 3 and ltv_fail_count % 3 == 0:
                    if self._notifier:
                        self._notifier.send(
                            "LTV超限警告",
                            f"币种: {loan_coin}\n数量: {loan_amt}\n失败原因: {reason}\n已连续失败: {ltv_fail_count} 次\n建议: 降低借币数量或增加抵押品",
                            platform="all"
                        )
            except Exception as e:
                self._root.after(0, lambda n=now, lc=loan_coin, la=loan_amt:
                    self._log_local(n, "借入\u274c", lc, la, "未知异常"))
                self._root.after(0, lambda a=attempt:
                    self._set_status(f"\u274c 第{a}次异常，继续尝试..."))
            base_rate = self._config_manager.get_config().borrow_rate
            delay = base_rate + random.uniform(0.01, 0.5)
            _time.sleep(delay)


    def _show_borrow_success(self, order_id, attempt, col_coin, col_amt, loan_coin, loan_amt):
        """借币成功：显示红色按钮 + 循环飞书通知"""
        self._ack_data = (order_id, col_coin, col_amt, loan_coin, loan_amt)
        # 显示红色按钮
        self._ack_btn.pack(side=tk.LEFT, padx=5)
        self._color_blink()
        self._set_status("借币成功！点击「已借到」关闭通知")
        # 启动飞书循环通知
        self._notifying = True
        threading.Thread(target=self._notify_loop, args=(order_id, col_coin, col_amt, loan_coin, loan_amt), daemon=True).start()
        self._refresh_all()

    def _color_blink(self):
        """按钮颜色闪烁一次"""
        self._ack_btn.config(bg="#ef4444")
        self._root.after(500, lambda: self._ack_btn.config(bg="#dc2626"))

    def _notify_loop(self, order_id, col_coin, col_amt, loan_coin, loan_amt):
        """每 5 秒推送飞书，直到用户点击已借到"""
        import time as _time
        while self._notifying:
            if self._notifier:
                self._notifier.send_stake_success(order_id, col_coin, col_amt, loan_coin, loan_amt)
            _time.sleep(5)

    def _on_ack_borrow(self):
        """点击已借到按钮：停止推送 + 隐藏按钮"""
        self._notifying = False
        self._ack_btn.pack_forget()
        self._set_status("借币完成")
        self._refresh_all()

    def _log_local(self, time_str, direction, coin, amount, reason=""):
        """本地写入借贷记录表格"""
        self._history_tree.insert("", 0, values=(time_str, direction, coin, amount, reason))

    def _do_borrow_async(self, col_coin, loan_coin, col_amt, loan_amt):
        """单次借币（保留兼容）"""
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
        """启动后自动：测试连接 + 刷新余额"""
        self._run_async(self._do_auto_init)

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

    def _start_ltv_timer(self):
        """每秒刷新一次 LTV"""
        if self._service:
            self._run_async(self._refresh_ltv)
        self._root.after(1000, self._start_ltv_timer)

    def _refresh_ltv(self):
        """仅刷新 LTV（轻量，不拉全部数据）"""
        try:
            ltv = self._service.get_current_ltv()
            self._root.after(0, lambda: self._ltv_var.set(ltv))
        except Exception:
            pass

    def run(self):
        self._root.mainloop()
