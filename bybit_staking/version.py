"""
閻楀牊婀版穱鈩冧紖
"""
VERSION = "3.9.7"
UPDATE_URL = "https://api.github.com/repos/lin03219/zhiya/releases/latest"
RELEASES_URL = "https://github.com/lin03219/zhiya/releases"

CHANGELOG = {
    "3.9.7": [
        "借币设置整合：LTV纠错、保护、飞书提醒合并为一个面板",
        "新增借币目标LTV参数(5~78%)，替代旧计算公式",
        "LTV纠错按参数执行：连续失败N次+等待+自动重发",
        "新增调整抵押品弹窗(追加/减少)，LTV实时同步",
        "借贷日志上限20条，自动滚动",
        "配额不足飞书提醒独立参数控制",
        "持仓LTV悬停提示强平阈值说明",
        "余额截断2位小数，防虚标划转失败",
    ],
}

