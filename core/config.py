"""配置加载与保存。"""

import json

from .paths import CONFIG_FILE

DEFAULT_CONFIG = {
    "bduss": "",
    "sign_interval": 3,
    "timeout": 30,
    "max_retries": 3,
    "proxy": "",
    "schedule_enabled": False,
    "schedule_time": "08:00",
    "schedule_mode": "onekey",
    "startup_minimize_to_tray": True,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "12306_query_interval": 3,
    "12306_auto_order_enabled": False,
    "12306_auto_order_dry_run": True,
    "12306_auto_order_passengers": [],
    "ui_theme": "system",
    "ui_color": "blue",
    "chrome_path": "",
    "chrome_user_data_dir": "",
    "chrome_debug_port": 9222,
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
