"""DrissionPage 浏览器辅助模块。

通过调试端口附加到本地 Chrome（或新启动一个调试端口的 Chrome），
**不替代 Cookie 查票**——只在「命中余票」之后协助：
  1. 自动跳转到 12306 购票页面
  2. 自动填入行程 / 选择车次 / 勾选乘客 / 选席别
  3. 停留在「滑块验证 + 提交订单」一步，由用户人工完成

设计原则：
  • 不做验证码绕过、不做点击提交，**人在环路**
  • 失败/超时立即抛错，不卡死调用方
  • 浏览器实例由本模块持有；进程退出时自动断开（不关闭浏览器）
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

try:
    from DrissionPage import ChromiumOptions, ChromiumPage
    from DrissionPage.errors import (
        ContextLostError,
        ElementNotFoundError,
        PageDisconnectedError,
    )
except ImportError as e:
    raise ImportError("缺少 DrissionPage：pip install DrissionPage>=4.1.0") from e

from .logger import logger
from .paths import _base_dir

LOGIN_URL = "https://kyfw.12306.cn/otn/resources/login.html"
HOME_URL = "https://kyfw.12306.cn/otn/leftTicket/init"
DAMAI_URL = "https://www.damai.cn"

DEFAULT_USER_DATA_DIR = _base_dir() / "chrome_profile"


def _detect_chrome_path() -> str:
    """探测本机 Chrome 可执行文件路径，找不到返回空字符串。"""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if Path(c).is_file():
            return str(c)
    found = shutil.which("chrome") or shutil.which("msedge")
    return found or ""


def detect_chrome_path() -> str:
    """供 UI 调用的探测接口。"""
    return _detect_chrome_path()


class BrowserSession:
    """封装一个 DrissionPage ChromiumPage，支持复用本地 Chrome 用户数据。

    生命周期：
      open()  → 启动 / 附加 Chrome
      goto()  → 打开指定页面
      close() → 仅断开连接（不关闭浏览器，便于用户继续手动操作）
    """

    def __init__(
        self,
        chrome_path: str = "",
        user_data_dir: str = "",
        debug_port: int = 9222,
        headless: bool = False,
    ):
        self.chrome_path = chrome_path or _detect_chrome_path()
        self.user_data_dir = user_data_dir or str(DEFAULT_USER_DATA_DIR)
        self.debug_port = int(debug_port)
        self.headless = headless
        self.page: ChromiumPage | None = None

    # ── 启动 ─────────────────────────────────────────────

    def open(self, on_log: Callable[[str, str], None] | None = None) -> ChromiumPage:
        """启动 / 附加 Chrome，返回 ChromiumPage 对象。"""
        log = on_log or (lambda m, t="info": logger.info(m))
        if not self.chrome_path:
            raise RuntimeError(
                "未找到 Chrome / Edge 浏览器，请在配置中手动指定 chrome_path"
            )

        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)

        opts = ChromiumOptions()
        opts.set_browser_path(self.chrome_path)
        opts.set_user_data_path(self.user_data_dir)
        opts.set_local_port(self.debug_port)
        opts.set_argument("--disable-blink-features", "AutomationControlled")
        opts.set_argument("--no-first-run")
        opts.set_argument("--no-default-browser-check")
        if self.headless:
            opts.headless()

        log(
            f"启动浏览器: {Path(self.chrome_path).name}（端口 {self.debug_port}, "
            f"用户目录 {self.user_data_dir}）",
            "info",
        )
        try:
            self.page = ChromiumPage(addr_or_opts=opts)
        except Exception as e:
            raise RuntimeError(
                f"启动浏览器失败: {type(e).__name__}: {e}\n"
                f"请确认 chrome_path 正确、debug_port 未被占用"
            ) from e
        return self.page

    # ── 通用导航 ─────────────────────────────────────────

    def goto(self, url: str, wait: float = 1.0) -> bool:
        if not self.page:
            self.open()
        try:
            self.page.get(url)
            time.sleep(wait)
            return True
        except (ContextLostError, PageDisconnectedError):
            return False

    def is_logged_in_12306(self) -> bool:
        """通过 cookie 中是否存在 tk 字段粗判 12306 登录态。"""
        if not self.page:
            return False
        try:
            cookies = self.page.cookies()
        except Exception:
            return False
        for c in cookies:
            name = c.get("name") if isinstance(c, dict) else getattr(c, "name", "")
            if name == "tk":
                return True
        return False

    # ── 12306：跳转购票页并自动填写 ──────────────────────

    def open_12306_query(
        self,
        from_name: str,
        to_name: str,
        train_date: str,
        on_log: Callable[[str, str], None] | None = None,
    ) -> bool:
        """打开 12306 查询页并填好出发/到达/日期，停在『查询』按钮前。

        返回 True 表示已停在查询按钮前；False 表示页面跳转失败。
        """
        log = on_log or (lambda m, t="info": logger.info(m))
        if not self.page:
            self.open(on_log)
        if not self.goto(HOME_URL, wait=2.0):
            log("打开 12306 首页失败", "fail")
            return False

        if not self.is_logged_in_12306():
            log(
                "⚠ 浏览器中尚未登录 12306。请在打开的窗口中手动完成登录后再点查询。",
                "info",
            )

        try:
            # 出发站
            from_input = self.page.ele("#fromStationText", timeout=3)
            from_input.input(from_name, clear=True)
            time.sleep(0.4)
            self.page.actions.type(("\ue015",))  # 下方向键 → 取首条建议
            time.sleep(0.2)
            self.page.actions.type(("\ue007",))  # 回车

            # 到达站
            to_input = self.page.ele("#toStationText", timeout=3)
            to_input.input(to_name, clear=True)
            time.sleep(0.4)
            self.page.actions.type(("\ue015",))
            time.sleep(0.2)
            self.page.actions.type(("\ue007",))

            # 日期
            date_input = self.page.ele("#train_date", timeout=3)
            date_input.input(train_date, clear=True)
            log(
                f"已填写：{from_name} → {to_name}  {train_date}（请在浏览器点查询并购票）",
                "ok",
            )
            return True
        except (ElementNotFoundError, Exception) as e:
            log(
                f"自动填表失败：{type(e).__name__}: {e}\n"
                f"已打开购票页，请手动操作。",
                "fail",
            )
            return False

    def open_12306_login(
        self, on_log: Callable[[str, str], None] | None = None
    ) -> bool:
        """仅打开 12306 登录页，让用户手动登录（程序不参与滑块/验证码）。"""
        log = on_log or (lambda m, t="info": logger.info(m))
        if not self.page:
            self.open(on_log)
        ok = self.goto(LOGIN_URL, wait=1.5)
        if ok:
            log("已打开 12306 登录页，请手动完成账号 + 滑块/短信验证。", "info")
        else:
            log("打开 12306 登录页失败。", "fail")
        return ok

    def open_damai(
        self,
        url_or_id: str = "",
        on_log: Callable[[str, str], None] | None = None,
    ) -> bool:
        """打开大麦网（指定演出 URL 或首页）。"""
        log = on_log or (lambda m, t="info": logger.info(m))
        target = url_or_id.strip() or DAMAI_URL
        if target.isdigit():
            target = f"https://detail.damai.cn/item.htm?id={target}"
        if not self.page:
            self.open(on_log)
        ok = self.goto(target, wait=1.5)
        if ok:
            log(f"已打开大麦网：{target}", "info")
        else:
            log("打开大麦网失败。", "fail")
        return ok

    # ── 关闭 ─────────────────────────────────────────────

    def close(self):
        """断开 DrissionPage 连接，**不关闭浏览器进程**（让用户继续操作）。"""
        if self.page:
            try:
                self.page.quit(timeout=3, force=False)
            except Exception:
                pass
            self.page = None


# ── 便捷工厂 ────────────────────────────────────────────


def make_browser_session(config: dict) -> BrowserSession:
    """根据 config 构造一个 BrowserSession（不主动启动）。"""
    return BrowserSession(
        chrome_path=config.get("chrome_path", ""),
        user_data_dir=config.get("chrome_user_data_dir", ""),
        debug_port=int(config.get("chrome_debug_port", 9222) or 9222),
    )


# ── 独立小工具：仅启动一个调试端口的 Chrome 供用户登录 ──


def launch_debug_chrome(
    chrome_path: str = "",
    user_data_dir: str = "",
    debug_port: int = 9222,
) -> subprocess.Popen | None:
    """直接 subprocess 启动一个监听调试端口的 Chrome（不通过 DrissionPage）。

    用于「让用户先在程序之外登录 12306，下次本工具自动复用」的场景。
    """
    chrome = chrome_path or _detect_chrome_path()
    if not chrome:
        raise RuntimeError("未找到 Chrome / Edge 可执行文件")
    profile = user_data_dir or str(DEFAULT_USER_DATA_DIR)
    Path(profile).mkdir(parents=True, exist_ok=True)
    args = [
        chrome,
        f"--remote-debugging-port={int(debug_port)}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://kyfw.12306.cn/otn/resources/login.html",
    ]
    return subprocess.Popen(args)
