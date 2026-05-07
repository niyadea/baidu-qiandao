"""Windows 注册表开机自启相关。"""

import os
import sys

if os.name == "nt":
    import winreg
else:
    winreg = None

STARTUP_REG_NAME = "BaiduTiebaSign"
START_MINIMIZED_ARG = "--start-minimized"
RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def build_startup_command(entry_file: str, minimized: bool) -> str:
    """构造写入注册表 Run 项的启动命令字符串。"""
    if getattr(sys, "frozen", False):
        parts = [sys.executable]
    else:
        parts = [sys.executable, os.path.abspath(entry_file)]
    if minimized:
        parts.append(START_MINIMIZED_ARG)
    return " ".join(f'"{p}"' for p in parts)


def get_startup_command() -> str | None:
    """读取当前注册表中的自启命令，未配置时返回 None。"""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH) as key:
            value, _ = winreg.QueryValueEx(key, STARTUP_REG_NAME)
            return value
    except FileNotFoundError:
        return None
    except OSError:
        return None


def is_startup_enabled() -> bool:
    return get_startup_command() is not None


def set_startup_enabled(enabled: bool, command: str):
    """启用或关闭开机自启。"""
    if winreg is None:
        raise OSError("当前系统不支持 Windows 开机启动项")
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(key, STARTUP_REG_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, STARTUP_REG_NAME)
            except FileNotFoundError:
                pass
