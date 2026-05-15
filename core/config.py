"""配置加载与保存。带：缺字段自动补默认、损坏文件自动备份后重建。"""

import json
import shutil
import time
from pathlib import Path

from .logger import logger
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
    "close_action": "ask",  # ask | minimize | quit
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
    "ollama_provider": "Ollama",
    "ollama_endpoints": [
        {"name": "本机 Ollama", "url": "http://localhost:11434", "provider": "Ollama"},
    ],
    "ollama_current_endpoint": "http://localhost:11434",
    "ollama_send_shortcut": "enter",
    "agent_kb_id": None,
    "agent_prompt": "",
}


def _backup_corrupted(path: Path) -> Path:
    """把损坏的配置备份成 config.json.broken-YYYYmmdd-HHMMSS。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(f".broken-{stamp}.json")
    try:
        shutil.copy(path, backup)
    except OSError as e:
        logger.warning(f"备份损坏配置失败: {e}")
    return backup


def _ensure_defaults(cfg: dict) -> tuple[dict, bool]:
    """补全缺失字段；返回 (补全后的 cfg, 是否被改动)。"""
    changed = False
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = v
            changed = True
    return cfg, changed


def load_config() -> dict:
    """加载配置：损坏自动备份 + 重建；缺字段自动补默认并写回。"""
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        backup = _backup_corrupted(CONFIG_FILE)
        logger.error(
            f"config.json 损坏 ({type(e).__name__}: {e}); 已备份到 {backup.name}, "
            f"使用默认配置重建。"
        )
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    if not isinstance(data, dict):
        backup = _backup_corrupted(CONFIG_FILE)
        logger.error(
            f"config.json 顶层不是对象 (got {type(data).__name__}); "
            f"已备份到 {backup.name}, 使用默认配置重建。"
        )
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    data, changed = _ensure_defaults(data)
    if changed:
        save_config(data)
    return data


def save_config(config: dict):
    """原子写：先写 .tmp 再 rename，避免半写损坏。"""
    tmp = CONFIG_FILE.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        tmp.replace(CONFIG_FILE)
    except OSError as e:
        logger.error(f"保存配置失败: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
