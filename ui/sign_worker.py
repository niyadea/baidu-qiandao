"""签到 / 一键 / 定时调度的后台线程逻辑。

本模块只关心"做什么"，所有 UI 反馈都通过 host 暴露的接口（_log、_ui、
_set_progress、_finish 等）回写到主界面，避免与 tkinter 控件直接耦合。
"""

import time as _time

import requests

from core import (
    DEFAULT_CONFIG,
    _format_user,
    get_followed_tiebas,
    get_session,
    get_tbs,
    get_user_info,
    save_config,
    sign_all_one_key,
    sign_one,
)


class SignWorker:
    """签到任务执行器，持有对 App 的引用以驱动 UI。"""

    def __init__(self, host):
        self.host = host

    # ── 公共入口 ─────────────────────────────────────────

    def _log_context(self, config: dict, action: str):
        host = self.host
        bduss = config.get("bduss", "")
        masked = (bduss[:6] + "..." + bduss[-4:]) if len(bduss) >= 10 else "(空)"
        proxy = config.get("proxy") or "无"
        host._ui(
            host._log,
            f"[{action}] BDUSS={masked} | 超时={config.get('timeout')}s "
            f"| 重试={config.get('max_retries')} 次 "
            f"| 间隔={config.get('sign_interval')}s | 代理={proxy}",
            "info",
        )

    def run_normal(self):
        """逐个签到。"""
        host = self.host
        config = host.config_data
        self._log_context(config, "逐个签到")
        session = get_session(config)
        host._current_session = session

        tbs = self._verify_login(
            session, config.get("timeout", DEFAULT_CONFIG["timeout"])
        )
        if not tbs:
            host._ui(host._finish)
            return

        save_config(config)
        self._run_normal_sign(session, tbs, config)

    def run_onekey(self):
        """一键签到。"""
        host = self.host
        config = host.config_data
        timeout = config.get("timeout", DEFAULT_CONFIG["timeout"])

        self._log_context(config, "一键签到")
        session = get_session(config)
        host._current_session = session
        tbs = self._verify_login(session, timeout)
        if not tbs:
            host._ui(host._finish)
            return

        save_config(config)
        host._ui(host._status_var.set, "正在执行一键签到...")
        host._ui(host._log, "正在调用一键签到接口...", "info")
        host._ui(host._progress.configure, maximum=1)

        start = _time.time()
        try:
            ok, msg, detail = sign_all_one_key(session, tbs, timeout)
        except requests.exceptions.ReadTimeout:
            host._ui(host._log, f"[错误] 一键签到请求超时 (>{timeout}秒)", "fail")
            host._ui(host._finish)
            return
        except requests.exceptions.RequestException as e:
            if not host._signing:
                host._ui(host._finish)
                return
            host._ui(
                host._log, f"[错误] 一键签到请求失败: {type(e).__name__}: {e}", "fail"
            )
            host._ui(host._finish)
            return

        host._ui(host._set_progress, 1)
        elapsed = _time.time() - start
        tag = "ok" if ok else "fail"
        prefix = "[OK]" if ok else "[FAIL]"
        host._ui(host._log, f"{prefix} {msg}（耗时 {elapsed:.2f}s）", tag)

        signed = detail.get("signedForumAmount", 0)
        failed = detail.get("signedForumAmountFail", 0)
        unsigned = detail.get("unsignedForumAmount", 0)
        grade = detail.get("gradeNoVip", 0)
        grade_vip = detail.get("gradeVip", 0)

        lines = [f"  已签到: {signed} 个"]
        if failed:
            lines.append(f"  签到失败: {failed} 个")
        if unsigned:
            lines.append(f"  未签到: {unsigned} 个")
        if grade:
            lines.append(f"  获得经验: {grade} (会员: {grade_vip})")
        for line in lines:
            host._ui(host._log, line, "info")

        host._ui(host._finish)

    def run_scheduled(self, mode: str):
        """定时任务：一键签到失败可自动回退逐个签到。"""
        host = self.host
        config = host.config_data
        timeout = config.get("timeout", DEFAULT_CONFIG["timeout"])

        self._log_context(config, f"定时-{mode}")
        session = get_session(config)
        host._current_session = session
        tbs = self._verify_login(session, timeout)
        if not tbs:
            host._ui(host._finish)
            return

        save_config(config)

        if mode == "onekey":
            host._ui(host._log, "正在尝试一键签到...", "info")
            host._ui(host._progress.configure, maximum=1)
            try:
                ok, msg, _ = sign_all_one_key(session, tbs, timeout)
            except requests.exceptions.RequestException as e:
                ok, msg = False, f"一键签到请求失败: {type(e).__name__}: {e}"

            if ok:
                host._ui(host._log, f"[OK] {msg}", "ok")
                host._ui(host._set_progress, 1)
                host._ui(host._finish)
                return

            host._ui(host._log, f"[FAIL] {msg}", "fail")
            host._ui(host._log, "自动切换为逐个签到...", "info")
            if not host._signing:
                host._ui(host._finish)
                return

        self._run_normal_sign(session, tbs, config)

    # ── 内部公共流程 ─────────────────────────────────────

    def _verify_login(self, session, timeout) -> str | None:
        host = self.host
        host._ui(host._status_var.set, "正在验证登录...")
        host._ui(host._log, f"正在验证登录状态（timeout={timeout}s）...", "info")
        start = _time.time()
        try:
            tbs = get_tbs(session, timeout)
        except requests.exceptions.RequestException as e:
            if not host._signing:
                return None
            host._ui(host._log, f"[错误] 登录验证失败: {type(e).__name__}: {e}", "fail")
            return None

        if not tbs:
            host._ui(host._log, "[错误] BDUSS 无效或已过期，请重新获取 Cookie", "fail")
            return None

        try:
            uinfo = get_user_info(session, timeout)
        except requests.exceptions.RequestException as e:
            host._ui(
                host._log, f"[警告] 获取用户信息失败: {type(e).__name__}: {e}", "info"
            )
            uinfo = None
        elapsed = _time.time() - start
        host._ui(
            host._log,
            f"登录成功，用户: {_format_user(uinfo)}（耗时 {elapsed:.2f}s, tbs={tbs[:8]}...）",
            "ok",
        )
        return tbs

    def _run_normal_sign(self, session, tbs, config):
        """逐个签到流程（手动 / 定时回退共用）。"""
        host = self.host
        timeout = config.get("timeout", DEFAULT_CONFIG["timeout"])
        max_retries = config.get("max_retries", DEFAULT_CONFIG["max_retries"])
        interval = config.get("sign_interval", DEFAULT_CONFIG["sign_interval"])

        host._ui(host._status_var.set, "正在获取贴吧列表...")
        host._ui(host._log, "正在获取关注的贴吧列表...", "info")
        list_start = _time.time()
        try:
            tiebas = get_followed_tiebas(session, timeout)
        except requests.exceptions.RequestException as e:
            if not host._signing:
                host._ui(host._finish)
                return
            host._ui(host._log, f"[错误] 获取列表失败: {type(e).__name__}: {e}", "fail")
            host._ui(host._finish)
            return

        if not tiebas:
            host._ui(
                host._log, "[错误] 未获取到任何贴吧（请确认账号已关注贴吧）", "fail"
            )
            host._ui(host._finish)
            return

        unsigned = [t for t in tiebas if not t["is_sign"]]
        signed_count = len(tiebas) - len(unsigned)
        list_elapsed = _time.time() - list_start
        host._ui(
            host._log,
            f"共 {len(tiebas)} 个贴吧, 已签到 {signed_count}, 待签到 {len(unsigned)}"
            f"（耗时 {list_elapsed:.2f}s）",
            "info",
        )

        if not unsigned:
            host._ui(host._log, "所有贴吧今日均已签到，无需操作。", "ok")
            host._ui(host._finish)
            return

        host._ui(host._progress.configure, maximum=len(unsigned))
        success = 0
        fail = 0
        run_start = _time.time()

        for i, tieba in enumerate(unsigned, 1):
            if not host._signing:
                host._ui(host._log, "签到已中止（用户停止）", "fail")
                break
            name = tieba["name"]
            host._ui(host._status_var.set, f"签到中 [{i}/{len(unsigned)}] {name}吧")
            one_start = _time.time()
            ok, msg = sign_one(session, tbs, name, timeout, max_retries)
            one_elapsed = _time.time() - one_start
            tag = "ok" if ok else "fail"
            prefix = "[OK]" if ok else "[FAIL]"
            host._ui(
                host._log,
                f"  {prefix} [{i}/{len(unsigned)}] {name}吧 - {msg}（{one_elapsed:.2f}s）",
                tag,
            )
            host._ui(host._set_progress, i)
            if ok:
                success += 1
            else:
                fail += 1
            if i < len(unsigned):
                _time.sleep(interval)

        total = _time.time() - run_start
        host._ui(
            host._log,
            f"\n签到完成: 成功 {success}, 失败 {fail}, 共 {success + fail}"
            f"（总耗时 {total:.2f}s）",
            "info",
        )
        host._ui(host._finish)
