"""百度贴吧自动签到工具 - 命令行入口。

实际逻辑位于 core/ 与 ui/ 包中，本文件仅作为兼容入口。
"""

from core.cli import cli_main

if __name__ == "__main__":
    cli_main()
