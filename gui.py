"""百度贴吧自动签到工具 - 图形界面入口。

实际实现位于 ui/ 与 core/ 包，本文件仅作为 PyInstaller 与历史调用兼容入口。
"""

from ui.app import main

if __name__ == "__main__":
    main()
