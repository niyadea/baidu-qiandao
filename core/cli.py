"""命令行交互流程。"""

import sys
import time

import requests

from .api import (
    _format_user,
    get_followed_tiebas,
    get_session,
    get_tbs,
    get_user_info,
    sign_one,
)
from .config import DEFAULT_CONFIG, load_config, save_config
from .paths import CONFIG_FILE


def print_bduss_guide():
    print(
        "\n如何获取 BDUSS:\n"
        "  1. 用浏览器打开 https://www.baidu.com 并登录你的百度账号\n"
        "  2. 按 F12 打开开发者工具\n"
        "  3. 切换到 Application(应用) 标签 -> 左侧 Cookies -> https://www.baidu.com\n"
        "  4. 找到名为 BDUSS 的条目，复制其 Value 值\n"
        "  5. 将该值粘贴到本工具中，或直接写入 config.json 的 bduss 字段\n"
    )


def setup_bduss(config: dict) -> bool:
    """引导用户设置 BDUSS，返回是否设置成功。"""
    print_bduss_guide()
    bduss = input("请输入 BDUSS (直接回车可稍后在 config.json 中手动填写): ").strip()
    if not bduss:
        print("已跳过，请手动编辑 config.json 填入 BDUSS 后重新运行。")
        return False

    timeout = config.get("timeout", DEFAULT_CONFIG["timeout"])
    config["bduss"] = bduss
    session = get_session(config)

    try:
        tbs = get_tbs(session, timeout)
    except requests.exceptions.ReadTimeout:
        print(f"[错误] 连接百度服务器超时 (>{timeout}秒)。")
        print("  建议: 在 config.json 中增大 timeout 值，或设置 proxy。")
        save_config(config)
        print(f"  BDUSS 已暂存到 {CONFIG_FILE}，修改配置后重新运行即可。")
        return False
    except requests.exceptions.ConnectionError:
        print("[错误] 无法连接到百度服务器，请检查网络连接。")
        config["bduss"] = ""
        return False

    if not tbs:
        config["bduss"] = ""
        print("[错误] BDUSS 无效或已过期，请检查后重试。")
        return False

    try:
        uinfo = get_user_info(session, timeout)
    except requests.exceptions.RequestException:
        uinfo = None
    display = _format_user(uinfo)

    print(f"[成功] 已验证登录，当前用户: {display}")
    save_config(config)
    print(f"BDUSS 已保存到 {CONFIG_FILE}")
    return True


def run_sign(config: dict):
    interval = config.get("sign_interval", DEFAULT_CONFIG["sign_interval"])
    timeout = config.get("timeout", DEFAULT_CONFIG["timeout"])
    max_retries = config.get("max_retries", DEFAULT_CONFIG["max_retries"])

    session = get_session(config)

    print("=" * 50)
    print("        百度贴吧自动签到工具")
    print("=" * 50)

    print("\n[*] 正在验证登录状态...")
    try:
        tbs = get_tbs(session, timeout)
    except requests.exceptions.ReadTimeout:
        print(f"[错误] 连接百度服务器超时 (>{timeout}秒)。")
        print("  建议: 在 config.json 中增大 timeout 值，或设置 proxy。")
        return
    except requests.exceptions.ConnectionError:
        print("[错误] 无法连接到百度服务器，请检查网络连接。")
        return

    if not tbs:
        print("[错误] BDUSS 无效或已过期，请重新设置。")
        setup_bduss(config)
        return

    try:
        uinfo = get_user_info(session, timeout)
    except requests.exceptions.RequestException:
        uinfo = None
    print(f"[OK] 登录成功，用户: {_format_user(uinfo)}")

    print("\n[*] 正在获取关注的贴吧列表...")
    try:
        tiebas = get_followed_tiebas(session, timeout)
    except requests.exceptions.RequestException as e:
        print(f"[错误] 获取贴吧列表失败: {e}")
        return
    if not tiebas:
        print("[错误] 未获取到任何贴吧，请确认账号已关注贴吧。")
        return

    unsigned = [t for t in tiebas if not t["is_sign"]]
    signed_count = len(tiebas) - len(unsigned)
    print(
        f"[统计] 共 {len(tiebas)} 个贴吧, "
        f"已签到 {signed_count} 个, 待签到 {len(unsigned)} 个"
    )

    if not unsigned:
        print("\n所有贴吧今日均已签到，无需操作。")
        return

    print(f"\n[*] 开始签到 ({len(unsigned)} 个)...\n")
    success = 0
    fail = 0
    for i, tieba in enumerate(unsigned, 1):
        name = tieba["name"]
        ok, msg = sign_one(session, tbs, name, timeout, max_retries)
        tag = "[OK]" if ok else "[FAIL]"
        print(f"  {tag} [{i}/{len(unsigned)}] {name}吧 - {msg}")
        if ok:
            success += 1
        else:
            fail += 1
        if i < len(unsigned):
            time.sleep(interval)

    print(f"\n{'=' * 50}")
    print(f"  签到完成: 成功 {success}, 失败 {fail}, 共 {success + fail}")
    print(f"{'=' * 50}")


def cli_main():
    config = load_config()
    if not config.get("bduss"):
        print("首次运行，需要设置百度账号凭证 (BDUSS)。")
        if not setup_bduss(config):
            sys.exit(0)
    run_sign(config)
