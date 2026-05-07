"""百度贴吧自动签到工具 - 图形界面主窗口。"""

import datetime
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import requests

from core import CONFIG_FILE, DEFAULT_CONFIG, LOG_FILE, load_config, logger, save_config

from .sign_worker import SignWorker
from .ticket_tab import TicketTab
from .tray import TrayManager
from .win_startup import (
    START_MINIMIZED_ARG,
    build_startup_command,
    is_startup_enabled,
    set_startup_enabled,
)

WINDOW_TITLE = "百度贴吧自动签到"
WINDOW_SIZE = "660x780"


class App(tk.Tk):
    def __init__(self, start_minimized: bool = False):
        super().__init__()
        self._start_minimized = start_minimized
        self.title(WINDOW_TITLE)
        self.resizable(False, False)
        w, h = (int(x) for x in WINDOW_SIZE.split("x"))
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.config_data = load_config()
        self._signing = False
        self._show_bduss = False
        self._scheduler_stop = threading.Event()
        self._current_session: requests.Session | None = None
        self._tray = TrayManager(WINDOW_TITLE, self._tray_show, self._tray_quit)
        self._sign_worker = SignWorker(self)
        self._log_date: datetime.date | None = None

        self._build_ui()
        self._load_config_to_ui()
        self._log_startup_status()
        self._start_scheduler()
        self.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)
        self.bind("<Unmap>", self._on_minimize)
        if self._start_minimized and self.config_data.get(
            "startup_minimize_to_tray", True
        ):
            self.withdraw()
            self.after(100, self._minimize_to_tray)

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 12, "pady": 5}

        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True, padx=4, pady=4)

        tieba_tab = ttk.Frame(self._notebook)
        self._notebook.add(tieba_tab, text="贴吧签到")

        self._build_bduss_frame(tieba_tab, pad)
        self._build_actions_frame(tieba_tab, pad)
        self._build_schedule_frame(tieba_tab, pad)
        self._build_startup_frame(tieba_tab, pad)
        self._build_path_frame(tieba_tab, pad)
        self._build_progress(tieba_tab, pad)
        self._build_log_frame(tieba_tab, pad)

        self._ticket_tab = TicketTab(
            self._notebook,
            config_data=self.config_data,
            on_save=lambda: save_config(self.config_data),
        )
        self._notebook.add(self._ticket_tab, text="抢票")

    def _build_bduss_frame(self, parent, pad):
        frm = ttk.LabelFrame(parent, text="BDUSS 设置", padding=8)
        frm.pack(fill="x", **pad)

        ttk.Label(frm, text="BDUSS:").grid(row=0, column=0, sticky="w")
        self._bduss_var = tk.StringVar()
        self._bduss_entry = ttk.Entry(
            frm, textvariable=self._bduss_var, show="*", width=52
        )
        self._bduss_entry.grid(row=0, column=1, padx=(6, 4), sticky="ew")

        self._toggle_btn = ttk.Button(
            frm, text="显示", width=5, command=self._toggle_show
        )
        self._toggle_btn.grid(row=0, column=2, padx=(0, 4))
        frm.columnconfigure(1, weight=1)

    def _build_actions_frame(self, parent, pad):
        frm = ttk.Frame(parent)
        frm.pack(fill="x", **pad)

        self._save_btn = ttk.Button(frm, text="保存 BDUSS", command=self._on_save)
        self._save_btn.pack(side="left", padx=(0, 8))

        self._sign_btn = ttk.Button(frm, text="逐个签到", command=self._on_sign)
        self._sign_btn.pack(side="left", padx=(0, 8))

        self._onekey_btn = ttk.Button(frm, text="一键签到", command=self._on_onekey)
        self._onekey_btn.pack(side="left", padx=(0, 8))

        self._stop_btn = ttk.Button(
            frm, text="停止签到", command=self._on_stop, state="disabled"
        )
        self._stop_btn.pack(side="left")

        self._status_var = tk.StringVar(value="就绪")
        ttk.Label(frm, textvariable=self._status_var).pack(side="right", padx=4)

    def _build_schedule_frame(self, parent, pad):
        frm = ttk.LabelFrame(parent, text="定时任务", padding=8)
        frm.pack(fill="x", **pad)

        self._schedule_enabled_var = tk.BooleanVar()
        ttk.Checkbutton(
            frm,
            text="启用定时签到",
            variable=self._schedule_enabled_var,
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(frm, text="执行时间:").grid(row=0, column=1, padx=(20, 4), sticky="e")

        self._hour_var = tk.StringVar(value="08")
        ttk.Spinbox(
            frm,
            from_=0,
            to=23,
            width=3,
            format="%02.0f",
            textvariable=self._hour_var,
            wrap=True,
        ).grid(row=0, column=2)

        ttk.Label(frm, text=":").grid(row=0, column=3)

        self._minute_var = tk.StringVar(value="00")
        ttk.Spinbox(
            frm,
            from_=0,
            to=59,
            width=3,
            format="%02.0f",
            textvariable=self._minute_var,
            wrap=True,
        ).grid(row=0, column=4)

        self._schedule_save_btn = ttk.Button(
            frm, text="保存设置", command=self._on_schedule_save
        )
        self._schedule_save_btn.grid(row=0, column=5, padx=(16, 0))

        ttk.Label(frm, text="签到方式:").grid(row=1, column=0, sticky="w", pady=(6, 0))

        self._schedule_mode_var = tk.StringVar(value="onekey")
        ttk.Radiobutton(
            frm,
            text="一键签到 (失败自动切换逐个)",
            variable=self._schedule_mode_var,
            value="onekey",
        ).grid(row=1, column=1, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Radiobutton(
            frm,
            text="逐个签到",
            variable=self._schedule_mode_var,
            value="normal",
        ).grid(row=1, column=4, columnspan=2, sticky="w", pady=(6, 0))

        self._schedule_info_var = tk.StringVar()
        ttk.Label(frm, textvariable=self._schedule_info_var).grid(
            row=2, column=0, columnspan=6, sticky="w", pady=(4, 0)
        )

    def _build_startup_frame(self, parent, pad):
        frm = ttk.LabelFrame(parent, text="开机自启", padding=8)
        frm.pack(fill="x", **pad)

        self._startup_enabled_var = tk.BooleanVar()
        ttk.Checkbutton(
            frm,
            text="开机自动启动",
            variable=self._startup_enabled_var,
            command=self._refresh_startup_info,
        ).grid(row=0, column=0, sticky="w")

        self._startup_minimize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frm,
            text="自启后缩小到托盘（无感启动）",
            variable=self._startup_minimize_var,
            command=self._refresh_startup_info,
        ).grid(row=0, column=1, padx=(18, 0), sticky="w")

        self._startup_save_btn = ttk.Button(
            frm, text="保存自启设置", command=self._on_startup_save
        )
        self._startup_save_btn.grid(row=0, column=2, padx=(16, 0))

        self._startup_info_var = tk.StringVar()
        ttk.Label(frm, textvariable=self._startup_info_var).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0)
        )

    def _build_path_frame(self, parent, pad):
        frm = ttk.Frame(parent)
        frm.pack(fill="x", **pad)
        ttk.Label(frm, text=f"配置: {CONFIG_FILE.name}  |  日志: {LOG_FILE.name}").pack(
            side="left"
        )
        ttk.Button(frm, text="打开目录", width=8, command=self._open_config_dir).pack(
            side="right"
        )

    def _build_progress(self, parent, pad):
        self._progress = ttk.Progressbar(parent, mode="determinate")
        self._progress.pack(fill="x", **pad)

    def _build_log_frame(self, parent, pad):
        frm = ttk.LabelFrame(parent, text="签到日志", padding=6)
        frm.pack(fill="both", expand=True, **pad)

        self._log_text = tk.Text(
            frm,
            height=14,
            state="disabled",
            font=("Consolas", 9),
            wrap="word",
        )
        scrollbar = ttk.Scrollbar(frm, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=scrollbar.set)

        self._log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._log_text.tag_configure("ok", foreground="#228B22")
        self._log_text.tag_configure("fail", foreground="#CC0000")
        self._log_text.tag_configure("info", foreground="#1E90FF")

    # ── 打开配置目录 ──────────────────────────────────────

    def _open_config_dir(self):
        os.startfile(str(CONFIG_FILE.parent))

    # ── 配置 ↔ UI ────────────────────────────────────────

    def _load_config_to_ui(self):
        cfg = self.config_data
        self._bduss_var.set(cfg.get("bduss", ""))

        self._schedule_enabled_var.set(cfg.get("schedule_enabled", False))
        t = cfg.get("schedule_time", "08:00")
        parts = t.split(":")
        self._hour_var.set(parts[0].zfill(2) if len(parts) >= 1 else "08")
        self._minute_var.set(parts[1].zfill(2) if len(parts) >= 2 else "00")
        self._schedule_mode_var.set(cfg.get("schedule_mode", "onekey"))
        self._refresh_schedule_info()
        self._startup_enabled_var.set(is_startup_enabled())
        self._startup_minimize_var.set(cfg.get("startup_minimize_to_tray", True))
        self._refresh_startup_info()

    def _read_schedule_time(self) -> str:
        h = self._hour_var.get().zfill(2)
        m = self._minute_var.get().zfill(2)
        return f"{h}:{m}"

    def _refresh_schedule_info(self):
        if self._schedule_enabled_var.get():
            t = self._read_schedule_time()
            mode = (
                "一键签到" if self._schedule_mode_var.get() == "onekey" else "逐个签到"
            )
            self._schedule_info_var.set(f"定时任务已启用，每天 {t} 自动执行{mode}")
        else:
            self._schedule_info_var.set("定时任务未启用")

    def _refresh_startup_info(self):
        if os.name != "nt":
            self._startup_info_var.set("当前系统不支持写入 Windows 开机启动项")
            return
        if self._startup_enabled_var.get():
            mode = (
                "启动后自动缩小到托盘"
                if self._startup_minimize_var.get()
                else "启动后显示窗口"
            )
            self._startup_info_var.set(f"开机自启已选择，{mode}")
        else:
            self._startup_info_var.set("开机自启未启用")

    def _log_startup_status(self):
        enabled = is_startup_enabled()
        mode = (
            "缩小到托盘"
            if self.config_data.get("startup_minimize_to_tray", True)
            else "显示窗口"
        )
        arg_mode = "，本次按自启参数启动" if self._start_minimized else ""
        self._log(
            f"开机自启状态: {'已启用' if enabled else '未启用'}，自启后{mode}{arg_mode}",
            "info",
        )

    # ── BDUSS 显示/隐藏 ─────────────────────────────────

    def _toggle_show(self):
        self._show_bduss = not self._show_bduss
        self._bduss_entry.configure(show="" if self._show_bduss else "*")
        self._toggle_btn.configure(text="隐藏" if self._show_bduss else "显示")

    # ── 日志输出 ─────────────────────────────────────────

    def _log(self, text: str, tag: str = ""):
        """写入界面日志：日期变化时清空并写入分隔行；时间戳前缀仅出现在界面，
        文件日志由 logger 自身的 formatter 负责加时间戳。"""
        self._roll_log_if_new_day()
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log_text.configure(state="normal")
        self._log_text.insert("end", f"[{ts}] {text}\n", tag)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")
        clean = text.strip()
        if clean:
            logger.info(clean)

    def _roll_log_if_new_day(self):
        today = datetime.date.today()
        if self._log_date == today:
            return
        if self._log_date is not None:
            self._log_text.configure(state="normal")
            self._log_text.delete("1.0", "end")
            self._log_text.configure(state="disabled")
        header = f"━━━━━━ {today.isoformat()} ━━━━━━"
        self._log_text.configure(state="normal")
        self._log_text.insert("end", header + "\n", "info")
        self._log_text.configure(state="disabled")
        self._log_date = today

    def _log_clear(self):
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")
        self._log_date = None

    # ── 按钮状态 ─────────────────────────────────────────

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self._save_btn.configure(state=state)
        self._sign_btn.configure(state=state)
        self._onekey_btn.configure(state=state)
        self._bduss_entry.configure(state=state)
        self._stop_btn.configure(state="normal" if busy else "disabled")

    # ── 停止签到 ─────────────────────────────────────────

    def _on_stop(self):
        self._signing = False
        if self._current_session:
            self._current_session.close()
        self._log("用户手动停止签到", "fail")
        self._status_var.set("已停止")

    # ── 保存 BDUSS ───────────────────────────────────────

    def _on_save(self):
        bduss = self._bduss_var.get().strip()
        if not bduss:
            messagebox.showwarning("提示", "BDUSS 不能为空")
            return
        self.config_data["bduss"] = bduss
        save_config(self.config_data)
        self._status_var.set("已保存")
        self._log("BDUSS 已保存到 config.json", "info")

    # ── 保存定时设置 ─────────────────────────────────────

    def _on_schedule_save(self):
        self.config_data["schedule_enabled"] = self._schedule_enabled_var.get()
        self.config_data["schedule_time"] = self._read_schedule_time()
        self.config_data["schedule_mode"] = self._schedule_mode_var.get()
        save_config(self.config_data)
        self._refresh_schedule_info()
        mode = "一键签到" if self._schedule_mode_var.get() == "onekey" else "逐个签到"
        self._log(
            f"定时设置已保存: {'启用' if self._schedule_enabled_var.get() else '关闭'}"
            f", 时间 {self._read_schedule_time()}, 方式: {mode}",
            "info",
        )

    # ── 保存开机自启设置 ─────────────────────────────────

    def _on_startup_save(self):
        enabled = self._startup_enabled_var.get()
        minimize = self._startup_minimize_var.get()
        self.config_data["startup_minimize_to_tray"] = minimize
        try:
            command = build_startup_command(__file__, minimize)
            set_startup_enabled(enabled, command)
        except OSError as e:
            self._startup_enabled_var.set(is_startup_enabled())
            self._refresh_startup_info()
            messagebox.showerror("保存失败", f"开机自启设置保存失败：{e}")
            self._log(f"[错误] 开机自启设置保存失败: {e}", "fail")
            return

        save_config(self.config_data)
        self._refresh_startup_info()
        self._log(
            f"开机自启设置已保存: {'启用' if enabled else '关闭'}"
            f"，自启后{'缩小到托盘' if minimize else '显示窗口'}",
            "info",
        )

    # ── 逐个签到 ─────────────────────────────────────────

    def _on_sign(self):
        bduss = self._bduss_var.get().strip()
        if not bduss:
            messagebox.showwarning("提示", "请先输入 BDUSS")
            return
        self.config_data["bduss"] = bduss
        self._signing = True
        self._set_busy(True)
        self._progress["value"] = 0
        self._log("──── 手动触发：逐个签到 ────", "info")
        threading.Thread(target=self._sign_worker.run_normal, daemon=True).start()

    # ── 一键签到 ─────────────────────────────────────────

    def _on_onekey(self):
        bduss = self._bduss_var.get().strip()
        if not bduss:
            messagebox.showwarning("提示", "请先输入 BDUSS")
            return
        self.config_data["bduss"] = bduss
        self._signing = True
        self._set_busy(True)
        self._progress["value"] = 0
        self._log("──── 手动触发：一键签到 ────", "info")
        threading.Thread(target=self._sign_worker.run_onekey, daemon=True).start()

    # ── 定时调度器 ───────────────────────────────────────

    def _start_scheduler(self):
        threading.Thread(target=self._scheduler_loop, daemon=True).start()

    def _scheduler_loop(self):
        last_run_date = None
        while not self._scheduler_stop.wait(15):
            if not self.config_data.get("schedule_enabled", False):
                continue
            if self._signing:
                continue

            now = datetime.datetime.now()
            schedule_time = self.config_data.get("schedule_time", "08:00")
            try:
                parts = schedule_time.split(":")
                target_h, target_m = int(parts[0]), int(parts[1])
            except (ValueError, IndexError):
                continue

            today = now.date()
            if last_run_date == today:
                continue

            target = now.replace(
                hour=target_h, minute=target_m, second=0, microsecond=0
            )
            if now >= target:
                last_run_date = today
                self._signing = True
                self._ui(self._set_busy, True)
                self._ui(self._progress.configure, value=0)

                mode = self.config_data.get("schedule_mode", "onekey")
                self._ui(
                    self._log,
                    f"──── 定时触发：{now.strftime('%H:%M:%S')} "
                    f"{'一键签到' if mode == 'onekey' else '逐个签到'} ────",
                    "info",
                )
                self._sign_worker.run_scheduled(mode)

    # ── 线程安全的 UI 更新 ───────────────────────────────

    def _ui(self, func, *args, **kwargs):
        if kwargs:
            self.after(0, lambda f=func, a=args, k=kwargs: f(*a, **k))
        else:
            self.after(0, func, *args)

    def _set_progress(self, value):
        self._progress["value"] = value

    def _finish(self):
        self._signing = False
        self._current_session = None
        self._set_busy(False)
        self._status_var.set("完成")

    # ── 系统托盘 ─────────────────────────────────────────

    def _on_minimize(self, event):
        if self.state() == "iconic":
            self.after(10, self._minimize_to_tray)

    def _minimize_to_tray(self):
        self.withdraw()
        self._tray.show()

    def _tray_show(self, icon=None, item=None):
        self.after(0, self._restore_window)

    def _restore_window(self):
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()

    def _tray_quit(self, icon=None, item=None):
        self._tray.stop()
        self.after(0, self._on_close)

    def _on_close(self):
        self._scheduler_stop.set()
        self._tray.stop()
        self.destroy()


def main():
    app = App(start_minimized=START_MINIMIZED_ARG in sys.argv[1:])
    app.mainloop()


if __name__ == "__main__":
    main()
