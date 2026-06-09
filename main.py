"""
bybit_staking - Bybit 质押借币桌面工具
"""
from bybit_staking.ui.main_window import MainWindow


def main():
    """程序入口"""
    app = MainWindow()
    app.run()


if __name__ == "__main__":
    main()
