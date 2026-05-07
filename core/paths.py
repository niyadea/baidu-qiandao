"""文件路径相关：兼容 PyInstaller 打包环境。"""

import sys
from pathlib import Path


def _base_dir() -> Path:
    """返回程序所在目录（兼容 PyInstaller 打包环境）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


CONFIG_FILE = _base_dir() / "config.json"
LOG_FILE = _base_dir() / "sign.log"
