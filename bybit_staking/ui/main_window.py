"""
妗岄潰涓荤晫闈?鈥?绠€娲佺増
宸︿晶淇℃伅鏍?+ 鍙充晶鎿嶄綔鍖?+ 寮圭獥锛堣缃€佹寔浠撱€佸垝杞級
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from typing import Optional

from config.config_manager import ConfigManager, AppConfig
from version import VERSION, UPDATE_URL, RELEASES_URL
from api.bybit_client import BybitClient, BybitApiError, VpnStatus, ApiRateLimit
from business.staking_service import StakingService
from notify.notifier import Notifier


def _center_window(win: tk.Toplevel, parent: tk.Tk):
    """灏嗗脊绐楀眳涓簬鐖剁獥鍙?""
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
    """鏍煎紡鍖?USD 閲戦"""
    if value >= 10000:
        return f"${value:,.0f}"
    elif value >= 1:
        return f"${value:,.2f}"
    else:
        return "$0.00"


class SettingsDialog(tk.Toplevel):
    """璁剧疆寮圭獥锛堥潪妯℃€侊級"""

    def __init__(self, parent, config_manager: ConfigManager, on_save_callback):
        super().__init__(parent)
        self._config_manager = config_manager
        self._config = config_manager.get_config()
        self._on_save = on_save_callback

        self.title("璁剧疆")
        self.resizable(False, False)
        self.transient(parent)

        self._build()
        _center_window(self, parent)

    def _build(self):
        pad = {"padx": 10, "pady": 5}

        api_frame = ttk.LabelFrame(self, text="Bybit API 瀵嗛挜", padding=10)
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
        ttk.Label(net_row, text="缃戠粶:").pack(side=tk.LEFT)
        self._network_var = tk.StringVar(value=self._config.network)
        ttk.Radiobutton(net_row, text="涓荤綉", variable=self._network_var, value="mainnet").pack(
            side=tk.LEFT, padx=10
        )
        ttk.Radiobutton(net_row, text="娴嬭瘯缃?, variable=self._network_var, value="testnet").pack(
            side=tk.LEFT
        )

        proxy_frame = ttk.LabelFrame(self, text="浠ｇ悊璁剧疆", padding=10)
        proxy_frame.pack(fill=tk.X, **pad)

        self._proxy_enabled = tk.BooleanVar(value=self._config.proxy.enabled)
        ttk.Checkbutton(proxy_frame, text="鍚敤浠ｇ悊", variable=self._proxy_enabled).pack(anchor=tk.W)

        ttk.Label(proxy_frame, text="HTTP / HTTPS 浠ｇ悊:").pack(anchor=tk.W)
        self._proxy_http = ttk.Entry(proxy_frame, width=55)
        self._proxy_http.pack(fill=tk.X, pady=2)
        proxy_val = self._config.proxy.http or self._config.proxy.https
        self._proxy_http.insert(0, proxy_val)

        notify_frame = ttk.LabelFrame(self, text="閫氱煡 Webhook", padding=10)
        notify_frame.pack(fill=tk.X, **pad)

        ttk.Label(notify_frame, text="椋炰功:").pack(anchor=tk.W)
        self._feishu = ttk.Entry(notify_frame, width=55)
        self._feishu.pack(fill=tk.X, pady=2)
        self._feishu.insert(0, self._config.notify.feishu_webhook)

        ttk.Label(notify_frame, text="閽夐拤:").pack(anchor=tk.W)
        self._dingtalk = ttk.Entry(notify_frame, width=55)
        self._dingtalk.pack(fill=tk.X, pady=2)
        self._dingtalk.insert(0, self._config.notify.dingtalk_webhook)

        # 鍊熷竵璇锋眰閫熺巼
        rate_frame = ttk.LabelFrame(self, text="鍊熷竵璇锋眰閫熺巼", padding=10)
        rate_frame.pack(fill=tk.X, **pad)
        ttk.Label(rate_frame, text="閫夋嫨璇锋眰闂撮殧锛堝疄闄呬細鍦ㄦ鍩虹涓婂姞 0.01~0.5 绉掗殢鏈烘诞鍔級:").pack(anchor=tk.W)
        self._rate_var = tk.StringVar(value=str(self._config.borrow_rate))
        rate_combo = ttk.Combobox(rate_frame, textvariable=self._rate_var,
            values=["0.5", "1.5", "2.5", "3.5", "4.5", "5.5"], width=10, state="readonly")
        rate_combo.pack(anchor=tk.W, pady=5)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, pady=(10, 5), padx=10)
        ttk.Button(btn_row, text="淇濆瓨", command=self._save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_row, text="鍙栨秷", command=self.destroy).pack(side=tk.RIGHT)

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
    """褰撳墠鎸佷粨寮圭獥 鈥?鏀寔杩樺竵"""

    def __init__(self, parent, service: Optional[StakingService]):
        super().__init__(parent)
        self._service = service
        self.title("褰撳墠鎸佷粨")
        self.geometry("600x400")
        self.resizable(True, True)
        self.transient(parent)

        self._build()
        _center_window(self, parent)

        if self._service:
            self._refresh()

    def _build(self):
        pad = {"padx": 10, "pady": 5}

        columns = ("鍊熷叆甯佺", "娆犳鎬婚", "鍒╃巼(鏃?", "鎿嶄綔")
        self._tree = ttk.Treeview(self, columns=columns, show="headings", height=8)
        self._tree.heading("鍊熷叆甯佺", text="鍊熷叆甯佺")
        self._tree.heading("娆犳鎬婚", text="娆犳鎬婚")
        self._tree.heading("鍒╃巼(鏃?", text="鍒╃巼(鏃?")
        self._tree.heading("鎿嶄綔", text="鎿嶄綔")
        self._tree.column("鍊熷叆甯佺", width=100, anchor=tk.CENTER)
        self._tree.column("娆犳鎬婚", width=130, anchor=tk.CENTER)
        self._tree.column("鍒╃巼(鏃?", width=100, anchor=tk.CENTER)
        self._tree.column("鎿嶄綔", width=80, anchor=tk.CENTER)
        self._tree.pack(fill=tk.BOTH, expand=True, **pad)

        # 鍙屽嚮琛屼篃鍙繕甯?
        self._tree.bind("<Double-1>", lambda e: self._repay_selected())

        self._summary_var = tk.StringVar(value="鎶垫娂鍝? --  |  鎬绘瑺娆? --  |  LTV: --")
        ttk.Label(self, textvariable=self._summary_var).pack(anchor=tk.W, **pad)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, **pad)
        ttk.Button(btn_row, text="涓€閿繕娓呭叏閮?, command=self._repay_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text="杩樺竵", command=self._repay_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text="鍒锋柊", command=self._refresh).pack(side=tk.RIGHT)

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
                    "[杩樺竵]",
                ))

            cols = ", ".join(f"{c.get('currency','')}: {c.get('amount','')}" for c in cl) or "--"
            self._summary_var.set(
                f"鎶垫娂鍝? {cols}  |  鎬绘瑺娆?USD: ${total_debt}  |  LTV: {ltv}"
            )
        except BybitApiError as e:
            messagebox.showerror("鏌ヨ澶辫触", str(e), parent=self)

    def _repay_selected(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("鎻愮ず", "璇峰厛閫夋嫨涓€绗旀寔浠?, parent=self)
            return
        values = self._tree.item(sel[0])["values"]
        coin = values[0]
        debt = values[1]
        self._show_repay_dialog(coin, debt)

    def _show_repay_dialog(self, coin, max_amount):
        dlg = tk.Toplevel(self)
        dlg.title(f"杩樺竵 - {coin}")
        dlg.geometry("300x180")
        dlg.resizable(False, False)
        dlg.transient(self)

        # 浣跨敤鍘熷娆犳鍊硷紝涓嶅仛鎴柇
        max_rounded = str(max_amount)




        ttk.Label(dlg, text=f"甯佺: {coin}\n娆犳鎬婚: {max_rounded}", padding=10).pack()

        row = ttk.Frame(dlg)
        row.pack(pady=5)
        ttk.Label(row, text="杩樻鏁伴噺:").pack(side=tk.LEFT)
        amt_var = tk.StringVar(value=max_rounded)
        amt_entry = ttk.Entry(row, textvariable=amt_var, width=14)
        amt_entry.pack(side=tk.LEFT, padx=5)

        def do_repay(amount=None):
            amt = amount if amount else amt_var.get().strip()
            if not amt:
                return
            try:
                rid = self._service.repay_smart(coin, amt)
                messagebox.showinfo("杩樻鎴愬姛", f"杩樻ID: {rid}", parent=dlg)
                dlg.destroy()
                self._refresh()
            except BybitApiError as e:
                messagebox.showerror("杩樻澶辫触", str(e), parent=dlg)

        ttk.Button(row, text="纭杩樻", command=lambda: do_repay()).pack(side=tk.LEFT, padx=5)
        ttk.Button(dlg, text="涓€閿繕娓?, command=lambda: do_repay(max_rounded)).pack(pady=5)

        _center_window(dlg, self)

    def _repay_all(self):
        if not self._service:
            return
        pos = self._service.get_position()
        bl = pos.get("borrowList", [])
        if not bl:
            messagebox.showinfo("鎻愮ず", "娌℃湁寰呰繕鎸佷粨", parent=self)
            return
        msg = "\n".join(f"{b['loanCurrency']}: {b['flexibleTotalDebt']}" for b in bl)
        if not messagebox.askyesno("涓€閿繕娓呭叏閮?, f"纭杩樻竻浠ヤ笅甯佺锛焅n\n{msg}", parent=self):
            return
        for b in bl:
            try:
                amt = str(b['flexibleTotalDebt'])
                self._service.repay_smart(b["loanCurrency"], amt)
            except BybitApiError as e:
                messagebox.showerror("杩樺竵澶辫触", f"{b['loanCurrency']}: {e}", parent=self)
        self._refresh()


class TransferDialog(tk.Toplevel):
    """鍒掕浆寮圭獥 鈥?缁熶竴璐︽埛 鈫?璧勯噾璐︽埛"""

    def __init__(self, parent, service: Optional[StakingService], on_success=None):
        super().__init__(parent)
        self._service = service
        self._on_success = on_success
        self.title("璐﹀唴鍒掕浆 鈥?缁熶竴 鈫?璧勯噾")
        self.resizable(False, False)
        self.transient(parent)

        self._build()
        _center_window(self, parent)

    def _build(self):
        pad = {"padx": 10, "pady": 5}

        ttk.Label(self, text="缁熶竴璐︽埛  鈫愨啋  璧勯噾璐︽埛", font=("", 10, "bold")).pack(pady=(10, 5))

        dir_frame = ttk.Frame(self)
        dir_frame.pack(fill=tk.X, **pad)
        ttk.Label(dir_frame, text="鏂瑰悜:", width=6).pack(side=tk.LEFT)
        self._direction = tk.StringVar(value="UNIFIED_TO_FUND")
        ttk.Radiobutton(
            dir_frame, text="缁熶竴 鈫?璧勯噾", variable=self._direction, value="UNIFIED_TO_FUND"
        ).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(
            dir_frame, text="璧勯噾 鈫?缁熶竴", variable=self._direction, value="FUND_TO_UNIFIED"
        ).pack(side=tk.LEFT)

        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X, **pad)
        ttk.Label(row1, text="甯佺:", width=6).pack(side=tk.LEFT)
        self._coin = ttk.Combobox(row1, values=["USDT", "USDC", "BTC", "ETH", "SOL"], width=12)
        self._coin.pack(side=tk.LEFT, padx=5)
        ttk.Label(row1, text="鏁伴噺:", width=6).pack(side=tk.LEFT)
        self._amount = ttk.Entry(row1, width=14)
        self._amount.pack(side=tk.LEFT)

        ttk.Button(self, text="鎵ц鍒掕浆", command=self._do_transfer).pack(pady=15)

    def _do_transfer(self):
        if not self._service:
            messagebox.showwarning("鎻愮ず", "璇峰厛閰嶇疆 API 瀵嗛挜", parent=self)
            return
        coin = self._coin.get().strip().upper()
        amount = self._amount.get().strip()
        if not coin or not amount:
            messagebox.showwarning("鎻愮ず", "璇峰～鍐欏竵绉嶅拰鏁伴噺", parent=self)
            return

        direction = self._direction.get()
        if direction == "UNIFIED_TO_FUND":
            from_acc, to_acc = "UNIFIED", "FUND"
            label = f"缁熶竴 鈫?璧勯噾: {amount} {coin}"
        else:
            from_acc, to_acc = "FUND", "UNIFIED"
            label = f"璧勯噾 鈫?缁熶竴: {amount} {coin}"

        if not messagebox.askyesno("纭鍒掕浆", label, parent=self):
            return
        try:
            tid = self._service.transfer(coin, amount, from_acc, to_acc)
            messagebox.showinfo("鍒掕浆鎴愬姛", f"鍒掕浆ID: {tid}", parent=self)
            if self._on_success:
                self._on_success()
        except BybitApiError as e:
            messagebox.showerror("鍒掕浆澶辫触", str(e), parent=self)


class MainWindow:
    """涓荤獥鍙?鈥?绠€娲佺増"""

    LEFT_WIDTH = 200

    def __init__(self):
        self._config_manager = ConfigManager()
        self._config = self._config_manager.load()
        self._service: Optional[StakingService] = None
        self._client: Optional[BybitClient] = None
        self._notifier: Optional[Notifier] = None
        self._init_client()

        self._root = tk.Tk()
        self._root.title("Bybit 璐ㄦ娂鍊熷竵")
        self._root.geometry("900x580")
        self._root.minsize(800, 520)

        self._root.update_idletasks()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        ww, wh = 900, 580
        self._root.geometry(f"{ww}x{wh}+{(sw - ww) // 2}+{(sh - wh) // 2}")

        self._borrow_looping = False
        self._BORROW_ERROR_MAP = {
            148012: "鎶垫娂鍝?USDT)浣欓涓嶈冻",
            148011: "鍊熷竵姹犱綑棰濅笉瓒?,
            148002: "鍊熷竵鏁伴噺涓嶅悎瑙?,
            148005: "瓒呭嚭灏忔暟绮惧害",
            10001: "鍙傛暟閿欒",
        }

        self._build_ui()
        self._root.after(300, self._auto_init)
        self._root.after(1000, self._ban_check_timer)
        self._root.after(5000, self._check_update)  # 棣栨妫€鏌ワ紝涔嬪悗姣?0鍒嗛挓

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

    # ==================== 鏋勫缓 UI ====================

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

        # 搴曢儴鐘舵€佹爮 鈥?涓夊垪锛氱姸鎬佹秷鎭?| VPN | --
        status_bar = ttk.Frame(self._root, relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self._status_var = tk.StringVar(value="灏辩华")
        ttk.Label(status_bar, textvariable=self._status_var, anchor=tk.W, padding=(5, 2)).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        # 鏇存柊鎸夐挳锛堝垵濮嬮殣钘忥級
        self._update_btn = ttk.Button(status_bar, text="鏈夋柊鐗堟湰", command=self._open_update_url)
        self._update_btn.pack(side=tk.RIGHT, padx=5)
        self._update_btn.pack_forget()  # 榛樿闅愯棌

        # VPN 鐘舵€佹斁鍦ㄧ姸鎬佹爮鍙充晶
        ttk.Separator(status_bar, orient=tk.VERTICAL).pack(side=tk.RIGHT, fill=tk.Y)
        self._vpn_bar_var = tk.StringVar(value="VPN 鏈祴璇?)
        ttk.Label(status_bar, textvariable=self._vpn_bar_var, anchor=tk.E, padding=(5, 2)).pack(
            side=tk.RIGHT
        )

    def _build_left_panel(self):
        pad = {"padx": 8, "pady": 3}
        f = self._left

        # 缃戠粶
        tk.Label(f, text="猬?缃戠粶", font=("", 9, "bold"), fg="#3b82f6").pack(anchor=tk.W, **pad)
        self._network_var = tk.StringVar(value=self._network_label())
        ttk.Label(f, textvariable=self._network_var, foreground="#2563eb").pack(anchor=tk.W, padx=16)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, **pad)

        # 鎬昏祫浜?
        tk.Label(f, text="猬?鎬昏祫浜?, font=("", 9, "bold"), fg="#10b981").pack(anchor=tk.W, **pad)
        self._total_var = tk.StringVar(value="$ --")
        ttk.Label(f, textvariable=self._total_var, foreground="#059669", font=("", 10, "bold")).pack(
            anchor=tk.W, padx=16
        )
        self._unified_var = tk.StringVar(value="缁熶竴: $ --")
        ttk.Label(f, textvariable=self._unified_var, font=("", 8)).pack(anchor=tk.W, padx=20)
        self._fund_var = tk.StringVar(value="璧勯噾: $ --")
        ttk.Label(f, textvariable=self._fund_var, font=("", 8)).pack(anchor=tk.W, padx=20)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, **pad)

        # 鎸佷粨 LTV
        tk.Label(f, text="猬?鎸佷粨 LTV", font=("", 9, "bold"), fg="#f59e0b").pack(anchor=tk.W, **pad)
        self._ltv_var = tk.StringVar(value="--")
        ttk.Label(f, textvariable=self._ltv_var, foreground="#d97706", font=("", 10, "bold")).pack(
            anchor=tk.W, padx=16
        )

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, **pad)

        # API 闄愰
        tk.Label(f, text="猬?API 闄愰", font=("", 9, "bold"), fg="#8b5cf6").pack(anchor=tk.W, **pad)
        self._api_used_var = tk.StringVar(value="--/--")
        ttk.Label(f, textvariable=self._api_used_var).pack(anchor=tk.W, padx=16)
        self._api_remain_var = tk.StringVar(value="鍓╀綑: --")
        ttk.Label(f, textvariable=self._api_remain_var, font=("", 8)).pack(anchor=tk.W, padx=16)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, **pad)

        # 璁剧疆
        # 鐗堟湰鍙?
        ttk.Label(f, text=f"v{VERSION}", foreground="#9ca3af", font=("", 7)).pack(pady=(10, 0))
        ttk.Button(f, text="妫€鏌ユ洿鏂?, width=8, command=self._check_update).pack()
        ttk.Button(f, text="璁剧疆", command=self._open_settings).pack(pady=10)

    def _build_right_panel(self):
        pad = {"pady": 5}
        f = self._right

        # 鍙戣捣鍊熷竵
        form = ttk.LabelFrame(f, text="鍙戣捣鍊熷竵", padding=10)
        form.pack(fill=tk.X, **pad)

        r1 = ttk.Frame(form)
        r1.pack(fill=tk.X, pady=2)
        self._collateral_coin = "USDT"  # 鍥哄畾 USDT
        self._collateral_amount = ""    # 鑷姩璁＄畻
        ttk.Label(r1, text="鎶垫娂鍝?", width=10).pack(side=tk.LEFT)
        ttk.Label(r1, text="USDT锛堣嚜鍔級", foreground="#059669").pack(side=tk.LEFT, padx=5)
        self._calc_var = tk.StringVar(value="--")
        ttk.Label(r1, textvariable=self._calc_var, font=("", 10, "bold"), foreground="#d97706").pack(side=tk.LEFT, padx=5)
        ttk.Button(r1, text="璁＄畻", width=5, command=self._manual_calc).pack(side=tk.LEFT)

        r2 = ttk.Frame(form)
        r2.pack(fill=tk.X, pady=2)
        ttk.Label(r2, text="鍊熷叆甯佺:", width=10).pack(side=tk.LEFT)
        self._loan_coin = ttk.Entry(r2, width=12)
        self._loan_coin.pack(side=tk.LEFT, padx=5)
        ttk.Label(r2, text="鏁伴噺:", width=6).pack(side=tk.LEFT)
        self._loan_amount = ttk.Entry(r2, width=14)
        self._loan_amount.pack(side=tk.LEFT, padx=5)

        btn_row = ttk.Frame(form)
        btn_row.pack(pady=(8, 0))
        self._borrow_btn = ttk.Button(btn_row, text="鍙戣捣鍊熷竵", command=self._do_borrow)
        self._borrow_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._ack_btn = tk.Button(btn_row, text="宸插€熷埌", fg="white", bg="#dc2626",
                                   font=("", 9, "bold"), command=self._on_ack_borrow)
        self._ltv_ok = False

        # 鍒濆闅愯棌
        self._ack_data = None  # 瀛樺偍鍊熷竵鎴愬姛鏁版嵁

        # 鍊熻捶璁板綍
        hist = ttk.LabelFrame(f, text="鍊熻捶璁板綍", padding=10)
        hist.pack(fill=tk.BOTH, expand=True, **pad)

        columns = ("鏃堕棿", "鏂瑰悜", "甯佺", "鏁伴噺", "鍘熷洜")
        self._history_tree = ttk.Treeview(hist, columns=columns, show="headings", height=8)
        self._history_tree.heading("鏃堕棿", text="鏃堕棿")
        self._history_tree.heading("鏂瑰悜", text="鏂瑰悜")
        self._history_tree.heading("甯佺", text="甯佺")
        self._history_tree.heading("鏁伴噺", text="鏁伴噺")
        self._history_tree.heading("鍘熷洜", text="鍘熷洜")
        self._history_tree.column("鏃堕棿", width=120, anchor=tk.CENTER)
        self._history_tree.column("鏂瑰悜", width=55, anchor=tk.CENTER)
        self._history_tree.column("甯佺", width=60, anchor=tk.CENTER)
        self._history_tree.column("鏁伴噺", width=80, anchor=tk.CENTER)
        self._history_tree.column("鍘熷洜", width=180, anchor=tk.W)
        self._history_tree.pack(fill=tk.BOTH, expand=True)

        # 蹇嵎鎿嶄綔
        actions = ttk.LabelFrame(f, text="蹇嵎鎿嶄綔", padding=8)
        actions.pack(fill=tk.X, **pad)

        ttk.Button(actions, text="褰撳墠鎸佷粨", command=self._open_positions).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="璐﹀唴鍒掕浆", command=self._open_transfer).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="鏌ヨ鍒╃巼", command=self._show_interest).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="娴嬭瘯杩炴帴", command=self._test_connection).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="鍏ㄩ儴鍒锋柊", command=self._refresh_all).pack(side=tk.RIGHT, padx=3)

    # ==================== 宸︿晶闈㈡澘鏇存柊 ====================

    def _network_label(self) -> str:
        return "涓荤綉" if self._config.network == "mainnet" else "娴嬭瘯缃?

    def _update_network_label(self):
        self._network_var.set(self._network_label())

    def _update_balances(self):
        """鏇存柊缁熶竴璐︽埛 + 璧勯噾璐︽埛浣欓"""
        if not self._service:
            return
        try:
            unified = self._service.get_unified_total_usd()
            fund = self._service.get_fund_total_usd()
            total = unified + fund
            self._root.after(0, lambda: self._total_var.set(_fmt_usd(total)))
            self._root.after(0, lambda: self._unified_var.set(f"缁熶竴: {_fmt_usd(unified)}"))
            self._root.after(0, lambda: self._fund_var.set(f"璧勯噾: {_fmt_usd(fund)}"))
            # 鍒锋柊鎸佷粨 LTV
            ltv = self._service.get_current_ltv()
            self._root.after(0, lambda: self._ltv_var.set(ltv))
        except BybitApiError as e:
            self._root.after(0, lambda e=e: self._set_status(f'浣欓鏌ヨ澶辫触: {e}'))
        except Exception as e:
            self._root.after(0, lambda e=e: self._set_status(f'浣欓寮傚父: {e}'))

    def _update_vpn_status(self, status: VpnStatus):
        icons = {"green": "[OK]", "yellow": "[WARN]", "red": "[ERR]"}
        icon = icons.get(status.level, "[?]")
        if status.connected:
            self._vpn_bar_var.set(f"VPN {icon} {status.latency_ms}ms")
        else:
            self._vpn_bar_var.set("VPN [ERR] 鏂繛")

    def _update_rate_limit(self, rl: ApiRateLimit):
        if rl.banned:
            self._api_used_var.set("宸插皝绂?")
            self._api_remain_var.set("绛夊緟瑙ｅ皝...")
        elif rl.remaining == 0 and rl.limit > 0:
            self._api_used_var.set(f"{rl.used}/{rl.limit} 宸茬敤瀹?")
            self._api_remain_var.set("鍓╀綑: 0 鏆傚仠璇锋眰")
        else:
            self._api_used_var.set(f"{rl.used}/{rl.limit}" if rl.limit > 0 else "--/--")
            self._api_remain_var.set(f"鍓╀綑: {rl.remaining}" if rl.limit > 0 else "鍓╀綑: --")

    def _get_current_rate_limit(self) -> ApiRateLimit:
        if self._client:
            return self._client.rate_limit
        return ApiRateLimit()

    # ==================== 寮圭獥 ====================

    def _open_settings(self):
        SettingsDialog(self._root, self._config_manager, self._reinit_client)

    def _open_positions(self):
        PositionsWindow(self._root, self._service)

    def _open_transfer(self):
        TransferDialog(self._root, self._service, on_success=self._refresh_all)

    def _show_interest(self):
        if not self._service:
            messagebox.showwarning("鎻愮ず", "璇峰厛閰嶇疆 API 瀵嗛挜")
            return
        self._set_status("姝ｅ湪鏌ヨ鍒╃巼...")
        self._run_async(self._do_show_interest)

    def _do_show_interest(self):
        try:
            rates = self._service.get_interest_rate()
            lines = []
            for r in rates:
                lines.append(f"{r.coin}:  鏃ュ埄鐜?{r.daily_rate}  |  骞村埄鐜?{r.yearly_rate}")
            text = "\n".join(lines) if lines else "鏃犳暟鎹?
            self._root.after(0, lambda: messagebox.showinfo("褰撳墠鍊熻捶鍒╃巼", text))
            self._root.after(0, lambda: self._set_status("鍒╃巼鏌ヨ瀹屾垚"))
        except BybitApiError as e:
            self._root.after(0, lambda: messagebox.showerror("鏌ヨ澶辫触", str(e)))

    # ==================== 鎿嶄綔 ====================

    def _test_connection(self):
        self._set_status("姝ｅ湪娴嬭瘯杩炴帴...")
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

        # 浣欓
        if self._service:
            self._run_async(self._update_balances)

        if vpn.connected and api_ok:
            self._root.after(0, lambda: self._set_status("杩炴帴姝ｅ父"))
        elif vpn.connected:
            self._root.after(0, lambda: self._set_status("VPN閫氫絾API涓嶉€氾紙妫€鏌ュ瘑閽ワ級"))
        else:
            self._root.after(0, lambda: self._set_status("鏃犳硶杩炴帴"))

    def _refresh_all(self):
        self._set_status("姝ｅ湪鍒锋柊...")
        self._run_async(self._do_refresh_all)

    def _do_refresh_all(self):
        if self._client:
            vpn = self._client.test_latency()
            self._root.after(0, lambda: self._update_vpn_status(vpn))

        if not self._service:
            self._root.after(0, lambda: self._set_status("璇峰厛閰嶇疆 API 瀵嗛挜"))
            return

        # 浣欓
        self._run_async(self._update_balances)

        # 鍊熻捶璁板綍
        try:
            borrow_history = self._service.get_borrow_history(limit=30)
            repay_history = self._service.get_repay_history(limit=30)
            combined = []
            for h in borrow_history:
                combined.append({
                    "time": h.get("createdTime", ""),
                    "direction": "鍊熷叆",
                    "coin": h.get("loanCoin", ""),
                    "amount": h.get("loanAmount", "0"),
                })
            for h in repay_history:
                combined.append({
                    "time": h.get("createdTime", ""),
                    "direction": "杩樻",
                    "coin": h.get("coin", ""),
                    "amount": h.get("repayAmount", "0"),
                })
            combined.sort(key=lambda x: x["time"], reverse=True)
            combined = combined[:30]
            self._root.after(0, lambda: self._update_history(combined))
        except BybitApiError as e:
            self._root.after(0, lambda: self._set_status(f"璁板綍鍒锋柊澶辫触: {e}"))

        rl = self._get_current_rate_limit()
        self._root.after(0, lambda: self._update_rate_limit(rl))

        self._root.after(0, lambda: self._set_status("鍒锋柊瀹屾垚"))

    def _update_history(self, items):
        for row in self._history_tree.get_children():
            self._history_tree.delete(row)
        for item in items:
            self._history_tree.insert("", tk.END, values=(
                item["time"], item["direction"], item["coin"], item["amount"], item.get("reason", ""),
            ))

    def _calc_collateral(self):
        """鑷姩璁＄畻鎵€闇€鎶垫娂鍝?""
        if not self._service:
            return
        loan_coin = self._loan_coin.get().strip().upper()
        loan_amt = self._loan_amount.get().strip()
        if not loan_coin or not loan_amt:
            return
        self._run_async(lambda: self._do_calc_collateral(loan_coin, loan_amt))

    def _manual_calc(self):
        """鎵嬪姩鐐瑰嚮銆岃绠椼€嶆寜閽?""
        if not self._service:
            return
        loan_coin = self._loan_coin.get().strip().upper()
        if not loan_coin:
            return
        self._set_status("姝ｅ湪璁＄畻...")
        self._loan_amount.delete(0, "end")
        self._run_async(lambda: self._auto_fill_max(loan_coin))

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
        # 甯佺鍙樹簡 鈫?娓呯┖鏁伴噺锛岄噸鏂拌嚜鍔ㄥ～鍏?
        if hasattr(self, "_last_coin") and self._last_coin and self._last_coin != loan_coin:
            self._auto_filling = True
            self._loan_amount.delete(0, "end")
            self._auto_filling = False
            loan_amt = ""
        self._last_coin = loan_coin
        if not loan_amt:
            self._calc_after_id = self._root.after(300, lambda c=loan_coin: self._run_async(lambda: self._auto_fill_max(c)))
        else:
            self._calc_after_id = self._root.after(300, lambda c=loan_coin, a=loan_amt: self._run_async(lambda: self._do_auto_calc(c, a)))

    def _auto_fill_max(self, loan_coin):
        """鑷姩璁＄畻鏈€澶у彲鍊熷苟濉叆鏁伴噺鏍?""
        try:
            # 甯佺宸插彉锛屼涪寮冩棫缁撴灉
            cur = self._loan_coin.get().strip().upper()
            if cur != loan_coin:
                return
            info = self._service.calculate_max_borrow(loan_coin)
            # 甯佺涓嶅彲鍊?
            if not info.get("coin_borrowable", True):
                lab = "璇ュ竵绉嶄笉鍙€? |  " + loan_coin
                self._root.after(0, lambda l=lab: self._calc_var.set(l))
                self._root.after(0, lambda: self._calc_var.config(foreground="#ef4444"))
                self._root.after(0, lambda: self._set_borrow_enabled(False))
                return
            if info["can_borrow"] and float(info["max_amount"]) > 0:
                max_amt = info["max_amount"]
                # 鐪熷疄鏈€澶у彲鍊燂紙鏄剧ず鐢級
                real_max = str(int(float(max_amt)))
                # 85% 鍐椾綑锛堝～鍏ョ敤锛?
                safe_amt = str(int(float(max_amt) * 0.85))
                lab = f"鏈€澶у彲鍊?{real_max} {loan_coin}  |  LTV " + info["current_ltv"]
                self._root.after(0, lambda l=lab: self._calc_var.set(l))
                self._root.after(0, lambda: self._calc_var.config(foreground="#10b981"))
                self._root.after(0, lambda: self._fill_amount(safe_amt, loan_coin))
            else:
                self._root.after(0, lambda: self._calc_var.set("鏃犳硶鍊熷竵  |  LTV " + info["current_ltv"]))
                self._root.after(0, lambda: self._calc_var.config(foreground="#ef4444"))
                self._root.after(0, lambda: self._set_borrow_enabled(False))
        except Exception:
            self._root.after(0, lambda: self._calc_var.set("璁＄畻澶辫触"))
            self._root.after(0, lambda: self._set_borrow_enabled(False))

    def _fill_amount(self, amt, loan_coin):
        """濉叆鏁伴噺锛屼繚鐣欐渶澶у彲鍊熸樉绀?""
        self._auto_filling = True
        self._loan_amount.delete(0, "end")
        self._loan_amount.insert(0, amt)
        self._auto_filling = False
        # 鐩存帴鍚敤鎸夐挳锛堟渶澶у彲鍊?脳0.85 涓€瀹氶€氳繃LTV妫€鏌ワ級
        self._root.after(0, lambda: self._set_borrow_enabled(True))

    def _do_auto_calc(self, loan_coin, loan_amt):
        try:
            # 甯佺宸插彉锛屼涪寮冩棫缁撴灉
            cur = self._loan_coin.get().strip().upper()
            if cur != loan_coin:
                return
            want = float(loan_amt)
            if want <= 0:
                return
            info = self._service.calculate_max_borrow(loan_coin)
            cur_ltv = info["current_ltv"]
            max_amt = info["max_amount"]
            total_debt = float(info["total_debt"])
            total_collateral = float(info["total_collateral"])
            if not info["can_borrow"]:
                lab = "鏃犳硶鍊熷竵  |  LTV " + cur_ltv
                self._root.after(0, lambda l=lab: self._calc_var.set(l))
                self._root.after(0, lambda: self._calc_var.config(foreground="#ef4444"))
                self._root.after(0, lambda: self._set_borrow_enabled(False))
                return
            price = self._service.get_coin_price(loan_coin)
            if price <= 0:
                self._root.after(0, lambda: self._calc_var.set("鏃犳硶鑾峰彇甯佷环"))
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
                lab = "LTV瓒呴檺!max" + max_amt + " " + loan_coin + "  |  " + cur_ltv
                self._root.after(0, lambda l=lab: self._calc_var.set(l))
                self._root.after(0, lambda: self._calc_var.config(foreground="#ef4444"))
                self._root.after(0, lambda: self._set_borrow_enabled(False))
        except Exception:
            self._root.after(0, lambda: self._calc_var.set("璁＄畻澶辫触"))
            self._root.after(0, lambda: self._set_borrow_enabled(False))

    def _set_borrow_enabled(self, enabled: bool):
        self._ltv_ok = enabled
        if enabled:
            self._borrow_btn.config(state="normal")
        else:
            self._borrow_btn.config(state="disabled")

    def _set_controls_enabled(self, enabled: bool):
        """灏佺鏃剁鐢?鍚敤鍊熷竵鐩稿叧鎺т欢"""
        state = "normal" if enabled else "disabled"
        self._borrow_btn.config(state=state)
        self._loan_coin.config(state=state)
        self._loan_amount.config(state=state)

    def _do_calc_collateral(self, loan_coin, loan_amt):
        self._do_auto_calc(loan_coin, loan_amt)

    def _do_borrow(self):
        if self._borrow_looping:
            self._borrow_looping = False
            self._borrow_btn.config(text="鍙戣捣鍊熷竵")
            self._set_status("宸插仠姝㈠惊鐜€熷竵")
            return
        if not self._service:
            messagebox.showwarning("鎻愮ず", "璇峰厛閰嶇疆 API 瀵嗛挜")
            return
        col_coin = self._collateral_coin
        loan_coin = self._loan_coin.get().strip().upper()
        loan_amt = self._loan_amount.get().strip()
        if not loan_coin or not loan_amt:
            messagebox.showwarning("鎻愮ず", "璇峰～鍐欏€熷叆甯佺鍜屾暟閲?)
            return
        try:
            info = self._service.calculate_max_borrow(loan_coin)
            if not info["can_borrow"]:
                msg = "褰撳墠LTV " + info["current_ltv"] + "\n宸叉棤鍙敤棰濆害"
                messagebox.showwarning("鏃犳硶鍊熷竵", msg)
                return
            want = float(loan_amt)
            if want > float(info["max_amount"]):
                msg = "褰撳墠LTV " + info["current_ltv"] + "\n鏈€澶у彲鍊?" + info["max_amount"] + " " + loan_coin + "\n浣犺緭鍏?" + loan_amt + " " + loan_coin
                messagebox.showwarning("瓒呭嚭LTV闄愬埗", msg)
                return
            price = self._service.get_coin_price(loan_coin)
            if price <= 0:
                messagebox.showwarning("閿欒", "鏃犳硶鑾峰彇甯佷环")
                return
            need_collateral = (want * price) / 0.80
            col_amt = f"{need_collateral:.2f}"
        except Exception as e:
            messagebox.showwarning("璁＄畻澶辫触", f"LTV妫€鏌ュ紓甯? {e}")
            return
        msg = "鎶垫娂 {} {}\n鍊熷叆 {} {}\n\n灏嗘瘡2-3绉掑皾璇曚竴娆★紝鐩村埌鎴愬姛".format(
            col_amt, col_coin, loan_amt, loan_coin)
        if not messagebox.askyesno("寰幆鍊熷竵", msg):
            return
        self._borrow_looping = True
        self._borrow_btn.config(text="鍋滄寰幆")
        self._set_status("寰幆鍊熷竵涓?..")
        self._run_async(lambda: self._loop_borrow(col_coin, loan_coin, col_amt, loan_amt))

    def _loop_borrow(self, col_coin, loan_coin, col_amt, loan_amt):
        """寰幆鍊熷竵锛?-3 绉掗殢鏈洪棿闅旓紝鐩村埌鎴愬姛鎴栨墜鍔ㄥ仠姝?""
        import random, time as _time
        ltv_fail_count = 0  # 杩炵画 LTV 澶辫触璁℃暟
        ERROR_MAP = {
            148012: "鎶垫娂鍝?USDT)浣欓涓嶈冻",
            148011: "鍊熷竵姹犱綑棰濅笉瓒?,
            148002: "鍊熷竵鏁伴噺涓嶅悎瑙?,
            148005: "瓒呭嚭灏忔暟绮惧害闄愬埗",
            10001: "璇锋眰鍙傛暟閿欒",
        }
        ERROR_TEXT = {
            "LTV_EXCEEDS_THRESHOLD": "瓒呰繃鏈€澶TV闄愬埗",
            "COLLATERAL_BALANCE_NOT_ENOUGH": "鎶垫娂鍝佷綑棰濅笉瓒?,
            "LOAN_FINANCE_BALANCE_NOT_ENO": "鍊熷竵姹犱綑棰濅笉瓒?,
            "LOAN_PLATFORM_QUOTA_NOT": "骞冲彴鍊熷竵閰嶉涓嶈冻",
            "LOAN_PLATFORM_QUOTA_NOT_ENO": "骞冲彴鍊熷竵閰嶉涓嶈冻",
            "LOAN_QUANTITY_NOT_ALLOWED": "鍊熷竵鏁伴噺涓嶅悎瑙?,
            "LOAN_AMOUNT_EXCEED_MAX": "瓒呭嚭鏈€澶у彲鍊熸暟閲?,
            "REPAY_AMOUNT_EXCEED_DEBT": "杩樻棰濊秴杩囨瑺娆?,
            "INSUFFICIENT_BALANCE_IN_S": "璐︽埛浣欓涓嶈冻",
            "PARAMETER_ERROR": "璇锋眰鍙傛暟閿欒",
            "REQUEST_PARAMETER_ERROR": "璇锋眰鍙傛暟閿欒",
        }
        attempt = 0
        while self._borrow_looping:
            attempt += 1
            now = _time.strftime("%m-%d %H:%M:%S")
            try:
                order_id = self._service.borrow(col_coin, loan_coin, col_amt, loan_amt)
                # 鎴愬姛
                self._root.after(0, lambda oid=order_id, n=now, lc=loan_coin, la=loan_amt:
                    self._log_local(n, "鍊熷叆\u2705", lc, la, "鎴愬姛"))
                self._borrow_looping = False
                self._root.after(0, lambda: self._borrow_btn.config(text="鍙戣捣鍊熷竵"))
                self._root.after(0, lambda oid=order_id, a=attempt, cc=col_coin, ca=col_amt, lc=loan_coin, la=loan_amt:
                    self._show_borrow_success(oid, a, cc, ca, lc, la))
                return
            except BybitApiError as e:
                reason = ERROR_MAP.get(e.code)
                if not reason:
                    # 瀛愪覆鍖归厤锛屾瘮鍓嶇紑鎴柇鏇村彲闈?
                    msg_upper = e.message.upper()
                    for key, val in ERROR_TEXT.items():
                        if key.upper() in msg_upper:
                            reason = val
                            break
                    if not reason:
                        reason = e.message[:40]
                if e.code == 148012 or "LTV" in e.message.upper() or "THRESHOLD" in e.message.upper():
                    ltv_fail_count += 1
                else:
                    ltv_fail_count = 0
                self._root.after(0, lambda n=now, lc=loan_coin, la=loan_amt, r=reason:
                    self._log_local(n, "鍊熷叆\u274c", lc, la, r))
                self._root.after(0, lambda a=attempt, r=reason:
                    self._set_status(f"\u274c 绗瑊a}娆″け璐? {r}"))
                # LTV 杩炵画澶辫触 3 娆★紝鎺ㄩ€侀涔?閽夐拤鎻愰啋
                if ltv_fail_count >= 3 and ltv_fail_count % 3 == 0:
                    if self._notifier:
                        self._notifier.send(
                            "LTV瓒呴檺璀﹀憡",
                            f"甯佺: {loan_coin}\n鏁伴噺: {loan_amt}\n澶辫触鍘熷洜: {reason}\n宸茶繛缁け璐? {ltv_fail_count} 娆n寤鸿: 闄嶄綆鍊熷竵鏁伴噺鎴栧鍔犳姷鎶煎搧",
                            platform="all"
                        )
            except Exception as e:
                self._root.after(0, lambda n=now, lc=loan_coin, la=loan_amt:
                    self._log_local(n, "鍊熷叆\u274c", lc, la, "鏈煡寮傚父"))
                self._root.after(0, lambda a=attempt:
                    self._set_status(f"\u274c 绗瑊a}娆″紓甯革紝缁х画灏濊瘯..."))
            base_rate = self._config_manager.get_config().borrow_rate
            delay = base_rate + random.uniform(0.01, 0.5)
            _time.sleep(delay)


    def _show_borrow_success(self, order_id, attempt, col_coin, col_amt, loan_coin, loan_amt):
        """鍊熷竵鎴愬姛锛氭樉绀虹孩鑹叉寜閽?+ 寰幆椋炰功閫氱煡"""
        self._ack_data = (order_id, col_coin, col_amt, loan_coin, loan_amt)
        # 鏄剧ず绾㈣壊鎸夐挳
        self._ack_btn.pack(side=tk.LEFT, padx=5)
        self._color_blink()
        self._set_status("鍊熷竵鎴愬姛锛佺偣鍑汇€屽凡鍊熷埌銆嶅叧闂€氱煡")
        # 鍚姩椋炰功寰幆閫氱煡
        self._notifying = True
        threading.Thread(target=self._notify_loop, args=(order_id, col_coin, col_amt, loan_coin, loan_amt), daemon=True).start()
        self._run_async(self._refresh_ltv)  # 鍊熷竵鎴愬姛鍚庡埛鏂?LTV
        self._refresh_all()

    def _color_blink(self):
        """鎸夐挳棰滆壊闂儊涓€娆?""
        self._ack_btn.config(bg="#ef4444")
        self._root.after(500, lambda: self._ack_btn.config(bg="#dc2626"))

    def _notify_loop(self, order_id, col_coin, col_amt, loan_coin, loan_amt):
        """姣?5 绉掓帹閫侀涔︼紝鐩村埌鐢ㄦ埛鐐瑰嚮宸插€熷埌"""
        import time as _time
        while self._notifying:
            if self._notifier:
                self._notifier.send_stake_success(order_id, col_coin, col_amt, loan_coin, loan_amt)
            _time.sleep(5)

    def _on_ack_borrow(self):
        """鐐瑰嚮宸插€熷埌鎸夐挳锛氬仠姝㈡帹閫?+ 闅愯棌鎸夐挳"""
        self._notifying = False
        self._ack_btn.pack_forget()
        self._set_status("鍊熷竵瀹屾垚")
        self._refresh_all()

    def _log_local(self, time_str, direction, coin, amount, reason=""):
        """鏈湴鍐欏叆鍊熻捶璁板綍琛ㄦ牸"""
        self._history_tree.insert("", 0, values=(time_str, direction, coin, amount, reason))

    def _do_borrow_async(self, col_coin, loan_coin, col_amt, loan_amt):
        """鍗曟鍊熷竵锛堜繚鐣欏吋瀹癸級"""
        try:
            order_id = self._service.borrow(col_coin, loan_coin, col_amt, loan_amt)
            self._root.after(0, lambda: messagebox.showinfo("鍊熷竵鎴愬姛", f"璁㈠崟鍙? {order_id}"))
            self._root.after(0, lambda: self._set_status(f"鍊熷竵鎴愬姛: {order_id}"))
            if self._notifier:
                self._notifier.send_stake_success(order_id, col_coin, col_amt, loan_coin, loan_amt)
            self._root.after(0, self._refresh_all)
        except BybitApiError as e:
            self._root.after(0, lambda: messagebox.showerror("鍊熷竵澶辫触", str(e)))
            self._root.after(0, lambda: self._set_status("鍊熷竵澶辫触"))

    # ==================== 宸ュ叿鏂规硶 ====================

    def _set_status(self, text: str):
        self._status_var.set(text)

    def _run_async(self, func):
        def safe_run():
            try:
                func()
            except Exception as e:
                import traceback
                self._root.after(0, lambda e=e: self._set_status(f"绾跨▼寮傚父: {e}"))
                traceback.print_exc()
        threading.Thread(target=safe_run, daemon=True).start()

    def _auto_init(self):
        """鍚姩鍚庤嚜鍔細娴嬭瘯杩炴帴 + 鍒锋柊浣欓"""
        self._run_async(self._do_auto_init)

    def _do_auto_init(self):
        # 娴?VPN
        vpn = VpnStatus()
        if self._client:
            vpn = self._client.test_latency()
            self._root.after(0, lambda: self._update_vpn_status(vpn))

        if not self._service:
            self._root.after(0, lambda: self._set_status("璇峰厛閰嶇疆 API 瀵嗛挜"))
            return

        # 浣欓
        self._run_async(self._update_balances)

        # API 杩為€氭€?
        api_ok = False
        try:
            self._service.get_account_info()
            api_ok = True
        except BybitApiError:
            pass

        rl = self._get_current_rate_limit()
        self._root.after(0, lambda: self._update_rate_limit(rl))

        if api_ok:
            self._root.after(0, lambda: self._set_status("杩炴帴姝ｅ父"))
        elif vpn.connected:
            self._root.after(0, lambda: self._set_status("VPN閫氫絾API涓嶉€氾紙妫€鏌ュ瘑閽ワ級"))
        else:
            self._root.after(0, lambda: self._set_status("鏃犳硶杩炴帴"))

    def _ban_check_timer(self):
        """姣?绉掓鏌?API 灏佺鐘舵€?""
        self._check_ban_status()
        self._root.after(5000, self._ban_check_timer)

    def _check_ban_status(self):
        """妫€鏌ュ苟鏇存柊灏佺鐘舵€?""
        if self._client:
            rl = self._client.rate_limit
            if rl.limit == 0:
                return
            if rl.banned:
                self._set_controls_enabled(False)
                remaining = int(rl.banned_until - __import__("time").time())
                if remaining > 0:
                    mins = remaining // 60
                    secs = remaining % 60
                    self._set_status(f"宸插皝绂侊紝绾?{mins}鍒唟secs}绉?鍚庤В灏?)
            else:
                self._set_controls_enabled(True)

    def _refresh_ltv(self):
        """浠呭埛鏂?LTV锛堣交閲忥紝涓嶆媺鍏ㄩ儴鏁版嵁锛?""
        try:
            ltv = self._service.get_current_ltv()
            self._root.after(0, lambda: self._ltv_var.set(ltv))
        except Exception:
            pass

    def _check_update(self):
        """鍚庡彴妫€鏌ユ洿鏂?+ 姣?0鍒嗛挓閲嶈瘯"""
        self._run_async(self._do_check_update_wrapper)
        # 30鍒嗛挓鍚庨噸璇?
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
            remote_ver = data.get("tag_name", "").lstrip("v")
            if remote_ver and remote_ver != VERSION:
                self._root.after(0, lambda: self._update_btn.pack(side=tk.RIGHT, padx=5))
                self._root.after(0, lambda: self._update_btn.config(text=f"v{remote_ver} 鍙敤"))
        except Exception:
            pass
    def _open_update_url(self):
        import webbrowser
        webbrowser.open(self._config.update_url.replace("version.json", "") or RELEASES_URL)

    def run(self):
        self._root.mainloop()
