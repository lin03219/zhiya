"""
bybit_staking - Bybit 质押借币桌面工具
"""
import sys
import os

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bybit_staking.ui.main_window import MainWindow


def main():
    """程序入口"""
    app = MainWindow()
    app.run()


if __name__ == "__main__":
    main()
