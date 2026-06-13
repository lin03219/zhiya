"""
bybit_staking - Bybit 质押借币桌面工具
"""
import sys
import os
import tkinter as tk
from tkinter import messagebox

from auth import checkAuth
from .ui.main_window import MainWindow


def main():
    """程序入口"""
    ok, reason = checkAuth()
    if not ok:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("启动校验失败", reason)
        sys.exit(1)

    app = MainWindow()
    app.run()


if __name__ == "__main__":
    main()
