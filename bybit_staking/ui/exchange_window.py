"""
闪兑窗口
展示统一账户各币种余额及可兑换USDT金额，支持逐币一键闪兑
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from typing import Optional

from ..api.bybit_client import BybitApiError
from ..business.exchange_service import ExchangeService, ExchangeableCoin


class ExchangeWindow(tk.Toplevel):
    """闪兑窗口"""

    def __init__(self, parent, service: ExchangeService):
        super().__init__(parent)
        self._service = service
        self._coins: list[ExchangeableCoin] = []
        self._row_frames: list[tk.Frame] = []
        self._coin_rows: dict = {}  # coin -> row frame

        self.title("闪兑")
        self.geometry("540x420")
        self.minsize(440, 280)
        self.resizable(True, True)
        self.transient(parent)

        self._build()
        self._center_on(parent)
        self._load_data()

    def _center_on(self, parent):
        """居中于父窗口"""
        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        ww = self.winfo_width()
        wh = self.winfo_height()
        x = px + (pw - ww) // 2
        y = py + (ph - wh) // 2
        self.geometry(f"+{x}+{y}")

    def _build(self):
        """构建界面"""
        # 标题
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=10, pady=(10, 5))
        ttk.Label(header, text="闪兑 — 统一账户", font=("", 11, "bold")).pack(side=tk.LEFT)
        self._loading_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self._loading_var, foreground="#9ca3af").pack(side=tk.RIGHT)

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)

        # 表头
        col_frame = ttk.Frame(self)
        col_frame.pack(fill=tk.X, padx=14, pady=(5, 2))
        ttk.Label(col_frame, text="币种", width=10, anchor=tk.W,
                  font=("", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(col_frame, text="数量", width=14, anchor=tk.CENTER,
                  font=("", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(col_frame, text="可兑换U", width=14, anchor=tk.CENTER,
                  font=("", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(col_frame, text="操作", anchor=tk.W,
                  font=("", 9, "bold")).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)

        # 可滚动的币种列表区域
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10)

        self._canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self._canvas.yview)
        self._row_container = ttk.Frame(self._canvas)

        self._row_container.bind("<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.create_window((0, 0), window=self._row_container, anchor=tk.NW, tags="container")
        self._canvas.configure(yscrollcommand=scrollbar.set)

        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 鼠标滚轮支持
        def _on_mousewheel(event):
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._canvas.bind("<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

        # 底部状态栏
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)
        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, padx=10, pady=5)
        self._status_var = tk.StringVar(value="就绪")
        ttk.Label(bottom, textvariable=self._status_var, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(bottom, text="一键兑换", command=self._batch_exchange).pack(side=tk.RIGHT, padx=3)
        ttk.Button(bottom, text="刷新", command=self._load_data).pack(side=tk.RIGHT)

    def _set_status(self, text: str):
        """更新状态栏"""
        self.after(0, lambda: self._status_var.set(text))

    def _load_data(self):
        """后台加载余额和报价"""
        self._set_status("正在加载...")
        self._loading_var.set("加载中...")
        # 清空旧行
        for f in self._row_frames:
            f.destroy()
        self._row_frames.clear()
        self._coin_rows.clear()

        def _do_load():
            try:
                # 获取可兑换币种列表和限额
                all_coins = self._service.getExchangeableBalances()
                limits = self._service.getCoinLimits()
                # 过滤：余额 >= 最小限额 且 未被禁用
                self._coins = []
                filtered = 0
                for ec in all_coins:
                    lim = limits.get(ec.coin, {})
                    if lim.get("disableFrom"):
                        filtered += 1
                        continue
                    min_from = float(lim.get("minFrom", "0"))
                    if float(ec.amount) < min_from:
                        filtered += 1
                        continue
                    self._coins.append(ec)
                if not self._coins:
                    self.after(0, lambda f=filtered: self._show_empty_filtered(f))
                    return
                # 逐币询价
                quotable_coins = []
                unquotable = 0
                for ec in self._coins:
                    updated = self._service.getQuote(ec.coin, ec.amount)
                    ec.quote_amount = updated.quote_amount
                    ec.quote_tx_id = updated.quote_tx_id
                    ec.quotable = updated.quotable
                    ec.error_msg = updated.error_msg
                    if ec.quotable:
                        quotable_coins.append(ec)
                    else:
                        unquotable += 1
                self._coins = quotable_coins
                self.after(0, lambda f=filtered + unquotable: self._populate(f))
            except BybitApiError as e:
                self.after(0, lambda: self._set_status(f"加载失败: {e}"))
                self.after(0, lambda: self._loading_var.set(""))
            except Exception as e:
                self.after(0, lambda: self._set_status(f"异常: {e}"))
                self.after(0, lambda: self._loading_var.set(""))

        threading.Thread(target=_do_load, daemon=True).start()

    def _show_empty(self, filtered=0):
        """显示空状态"""
        self._loading_var.set("")
        msg = "暂无可兑换币种"
        if filtered:
            msg += f"（已过滤 {filtered} 个低额币种）"
        self._set_status(msg)
        ttk.Label(self._row_container, text=msg,
                  foreground="gray").pack(pady=30)

    def _show_empty_filtered(self, filtered=0):
        self._show_empty(filtered)

    def _populate(self, filtered=0):
        """填充币种列表"""
        self._loading_var.set("")
        count = 0
        for ec in self._coins:
            row = ttk.Frame(self._row_container)
            row.pack(fill=tk.X, pady=1)
            self._row_frames.append(row)
            self._coin_rows[ec.coin] = row

            # 币种
            ttk.Label(row, text=ec.coin, width=10, anchor=tk.W).pack(side=tk.LEFT, padx=2)

            # 数量 (3位小数)
            amount_str = f"{float(ec.amount):.3f}"
            ttk.Label(row, text=amount_str, width=14, anchor=tk.CENTER).pack(side=tk.LEFT, padx=2)

            # 可兑换U (3位小数) / 报错信息
            if ec.quotable and ec.quote_amount:
                quote_str = f"{float(ec.quote_amount):.3f}"
                quotable = True
                quote_color = "black"
            elif ec.error_msg:
                quote_str = ec.error_msg[:30]  # 截短显示
                quotable = False
                quote_color = "#dc2626"  # 红色
            else:
                quote_str = "--"
                quotable = False
                quote_color = "black"
            ttk.Label(row, text=quote_str, width=20, anchor=tk.CENTER,
                      foreground=quote_color).pack(side=tk.LEFT, padx=2)

            # 操作按钮
            btn_container = ttk.Frame(row)
            btn_container.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)
            if quotable:
                btn = ttk.Button(btn_container, text="确认闪兑", width=9,
                                 command=lambda c=ec, b=None: self._do_exchange(c))
                btn.pack(side=tk.LEFT)
            else:
                disabled_btn = ttk.Button(btn_container, text="不可兑换", width=9, state=tk.DISABLED)
                disabled_btn.pack(side=tk.LEFT)

            count += 1

        msg = f"共 {count} 个可兑换币种"
        if filtered:
            msg += f"（已过滤 {filtered} 个低额）"
        self._set_status(msg)
    def _batch_exchange(self):
        """一键批量兑换所有币种"""
        if not self._coins:
            messagebox.showinfo("提示", "没有可兑换的币种")
            return
        total = len(self._coins)
        if not messagebox.askyesno("确认", f"将逐个兑换全部 {total} 个币种为 USDT，确定？"):
            return

        def _run_batch():
            failed = []
            for i, coin in enumerate(list(self._coins)):
                self.after(0, lambda p=i+1, t=total, c=coin.coin:
                    self._set_status(f"批量兑换 {p}/{t}: {c}..."))
                try:
                    # 询价
                    updated = self._service.getQuote(coin.coin, coin.amount)
                    if not updated.quotable or not updated.quote_tx_id:
                        failed.append(f"{coin.coin}: 询价失败 {updated.error_msg}")
                        continue
                    # 成交
                    self._service.executeExchange(updated.quote_tx_id)
                    # 删行
                    self.after(0, lambda c=coin: self._on_exchange_success_silent(c))
                except BybitApiError as e:
                    failed.append(f"{coin.coin}: {e}")
                except Exception as e:
                    failed.append(f"{coin.coin}: {e}")
            # 完成
            remaining = len(self._coins)
            msg = f"批量兑换完成 — 剩余 {remaining} 个"
            if failed:
                msg += f"，{len(failed)} 个失败"
                self.after(0, lambda f=failed: messagebox.showwarning(
                    "部分失败", "\n".join(f[:5]) + ("\n..." if len(f) > 5 else "")))
            else:
                self.after(0, lambda: messagebox.showinfo("完成", "全部兑换成功"))
            self.after(0, lambda m=msg: self._set_status(m))

        threading.Thread(target=_run_batch, daemon=True).start()

    def _on_exchange_success_silent(self, coin: ExchangeableCoin):
        """静默删行（用于批量兑换，不弹窗）"""
        if coin.coin in self._coin_rows:
            self._coin_rows[coin.coin].destroy()
            del self._coin_rows[coin.coin]
            self._row_frames = [f for f in self._row_frames if f.winfo_exists()]
            self._coins = [c for c in self._coins if c.coin != coin.coin]
        if len(self._coins) == 0:
            self._show_empty()

    def _on_exchange_success(self, coin: ExchangeableCoin):
        """兑换成功后删除该行，不刷新整个列表"""
        if coin.coin in self._coin_rows:
            self._coin_rows[coin.coin].destroy()
            del self._coin_rows[coin.coin]
            self._row_frames = [f for f in self._row_frames if f.winfo_exists()]
            self._coins = [c for c in self._coins if c.coin != coin.coin]
        count = len(self._coins)
        self._set_status(f"{coin.coin} 兑换成功 — 剩余 {count} 个币种")
        messagebox.showinfo("兑换成功", f"{coin.coin} -> USDT")
        # 如果全兑完，显示空状态
        if count == 0:
            self._show_empty()

    def _do_exchange(self, coin: ExchangeableCoin):
        """执行闪兑（每次点击都重新询价，避免报价过期）"""
        self._set_status(f"兑换 {coin.coin}...")

        def _run():
            last_error = ""
            for _ in range(3):  # 报价过期自动重试最多3次
                try:
                    # 重新询价
                    updated = self._service.getQuote(coin.coin, coin.amount)
                    if not updated.quotable or not updated.quote_tx_id:
                        last_error = f"询价失败: {updated.error_msg}"
                        continue
                    # 立刻成交
                    result = self._service.executeExchange(updated.quote_tx_id)
                    rdata = result.get("result", {})
                    status = rdata.get("exchangeStatus", rdata.get("status", "处理中"))
                    self.after(0, lambda c=coin: self._on_exchange_success(c))
                    return
                except BybitApiError as e:
                    last_error = str(e)
                    if "time out" in last_error or "700008" in last_error:
                        continue
                    break
                except Exception as e:
                    last_error = f"异常: {e}"
                    break
            self.after(0, lambda: messagebox.showerror("兑换失败", last_error, parent=self))
            self.after(0, lambda: self._set_status(f"{coin.coin} 失败"))

        threading.Thread(target=_run, daemon=True).start()

