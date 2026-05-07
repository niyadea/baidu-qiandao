"""百度贴吧签到工具核心层（业务逻辑、API、配置）。

为兼容历史代码，重导出核心符号，使 `from core import logger, sign_one, ...` 一站式可用。
"""

from .api import (
    SIGN_KEY,
    _client_sign,
    _format_user,
    get_followed_tiebas,
    get_session,
    get_tbs,
    get_user_info,
    sign_all_one_key,
    sign_one,
    sign_via_client,
    sign_via_web,
)
from .cli import cli_main, print_bduss_guide, run_sign, setup_bduss
from .config import DEFAULT_CONFIG, load_config, save_config
from .logger import logger
from .paths import CONFIG_FILE, LOG_FILE, _base_dir

__all__ = [
    "CONFIG_FILE",
    "DEFAULT_CONFIG",
    "LOG_FILE",
    "SIGN_KEY",
    "_base_dir",
    "_client_sign",
    "_format_user",
    "cli_main",
    "get_followed_tiebas",
    "get_session",
    "get_tbs",
    "get_user_info",
    "load_config",
    "logger",
    "print_bduss_guide",
    "run_sign",
    "save_config",
    "setup_bduss",
    "sign_all_one_key",
    "sign_one",
    "sign_via_client",
    "sign_via_web",
]
