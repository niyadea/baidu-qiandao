"""智能桌面助手 — Win11 Fluent Design 主窗口。

UI 设计：
  • 全局视觉常量：ui.styling
  • 自定义控件：ui.widgets（Card / SectionCard / LogView / IntSpinBox / SelectableList）
  • 主窗口 + Toplevel 都会尝试套 Mica 材质（Win11 22000+ 自动生效，旧系统降级）
  • Worker 通过线程安全回调与 UI 通信
"""

from __future__ import annotations

import datetime
import os
import sys
import threading
import tkinter as tk
import traceback
from tkinter import messagebox

import customtkinter as ctk
import requests

from core.agent_actions import AgentActionRegistry
from core import (
    CONFIG_FILE,
    DEFAULT_CONFIG,
    LOG_FILE,
    load_config,
    logger,
    save_config,
)

from . import styling as S
from .ollama_tab import OllamaTab
from .sign_worker import SignWorker
from .ticket_tab import TicketTab
from .tray import TrayManager
from .widgets import (
    LogView,
    PivotTabs,
    ProgressWithLabel,
    SectionCard,
    accent_button,
    danger_button,
    standard_button,
    subtle_button,
)
from .win_startup import (
    START_MINIMIZED_ARG,
    build_startup_command,
    is_startup_enabled,
    set_startup_enabled,
)

WINDOW_TITLE = "智能桌面助手"
DEFAULT_SIZE = (920, 940)
MIN_SIZE = (820, 760)


class App(ctk.CTk):
    def __init__(self, start_minimized: bool = False):
        super().__init__()
        self._start_minimized = start_minimized

        self.config_data = load_config()
        S.apply_theme(
            self.config_data.get("ui_theme", "system"),
            self.config_data.get("ui_color", "blue"),
        )

        self._init_window()
        self._install_exception_hook()

        self._signing = False
        self._show_bduss = False
        self._scheduler_stop = threading.Event()
        self._current_session: requests.Session | None = None
        self._tray = TrayManager(WINDOW_TITLE, self._tray_show, self._tray_quit)
        self._sign_worker = SignWorker(self)
        self._agent_drawer_visible = False

        self._build_ui()
        self._load_config_to_ui()
        self._log_startup_status()
        self._start_scheduler()

        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.bind("<Unmap>", self._on_minimize)
        self._close_dialog: ctk.CTkToplevel | None = None

        # Win11 风格的标题栏 + 边框装饰
        self.after(50, lambda: S.apply_window_chrome(self))

        if self._start_minimized and self.config_data.get(
            "startup_minimize_to_tray", True
        ):
            self.withdraw()
            self.after(100, self._minimize_to_tray)

    # ── 窗口 / 异常 ─────────────────────────────────────

    def _init_window(self):
        self.title(WINDOW_TITLE)
        self.minsize(*MIN_SIZE)
        w, h = DEFAULT_SIZE
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2 - 20
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(fg_color=S.WIN_BG)

    def _install_exception_hook(self):
        original = self.report_callback_exception

        def hook(exc, val, tb):
            logger.error(
                "UI 异常:\n" + "".join(traceback.format_exception(exc, val, tb))
            )
            try:
                messagebox.showerror(
                    "程序异常",
                    f"发生了未处理异常:\n\n{type(val).__name__}: {val}\n\n"
                    f"详细堆栈已写入 {LOG_FILE.name}",
                )
            except Exception:
                pass
            original(exc, val, tb)

        self.report_callback_exception = hook

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self):
        # 顶部菜单栏（仅保留主题切换图标，标题由系统标题栏承担）
        menubar = ctk.CTkFrame(self, fg_color="transparent", height=32)
        menubar.pack(fill="x", padx=S.SPACE_XL, pady=(S.SPACE_SM, 0))
        menubar.pack_propagate(False)

        self._agent_btn = accent_button(
            menubar,
            "Agent",
            self._toggle_agent_drawer,
            width=76,
            height=28,
        )
        self._agent_btn.pack(side="right", padx=(S.SPACE_SM, 0))

        current_theme = self.config_data.get("ui_theme", "system")
        self._theme_var = tk.StringVar(value=current_theme)
        self._theme_btn = subtle_button(
            menubar,
            text=self._theme_icon(current_theme),
            command=self._cycle_theme,
            width=28,
            height=28,
            font=S.font_body(14),
        )
        self._theme_btn.pack(side="right")

        self._main_shell = ctk.CTkFrame(self, fg_color="transparent")
        self._main_shell.pack(
            fill="both", expand=True,
            padx=S.SPACE_XL, pady=(S.SPACE_XS, S.SPACE_XL),
        )

        # Pivot Tabs（贴吧风格：底部 accent 下划线指示器）
        self._tabview = PivotTabs(self._main_shell)
        self._tabview.pack(
            side="left", fill="both", expand=True,
        )

        tieba_tab = self._tabview.add("贴吧签到")
        ticket_tab_frame = self._tabview.add("抢票 (12306 / 大麦)")

        self._build_tieba_tab(tieba_tab)

        self._ticket_tab = TicketTab(
            ticket_tab_frame,
            config_data=self.config_data,
            on_save=lambda: save_config(self.config_data),
        )
        self._ticket_tab.pack(fill="both", expand=True)

        self._agent_actions = self._build_agent_actions()
        self._build_agent_drawer()

    def _build_agent_actions(self) -> AgentActionRegistry:
        registry = AgentActionRegistry()
        registry.register("app.status", "读取当前页面和任务状态", self._agent_status)
        registry.register("app.switch_tab", "切换到贴吧、12306 或大麦页面", self._agent_switch_tab)
        registry.register("tieba.sign_all", "执行贴吧一键签到", self._agent_tieba_sign_all)
        registry.register("tieba.sign_normal", "执行贴吧逐个签到", self._agent_tieba_sign_normal)
        registry.register("tieba.stop", "停止当前贴吧签到任务", self._agent_tieba_stop)
        registry.register("ticket.query", "开始 12306 余票查询", self._agent_ticket_start)
        registry.register("ticket.start_polling", "开始 12306 余票轮询", self._agent_ticket_start)
        registry.register("ticket.stop_polling", "停止 12306 余票轮询", self._agent_ticket_stop)
        registry.register("damai.query_stock", "开始大麦库存查询", self._agent_damai_start)
        registry.register("damai.start_polling", "开始大麦库存轮询", self._agent_damai_start)
        registry.register("damai.stop_polling", "停止大麦库存轮询", self._agent_damai_stop)
        return registry

    def _build_agent_drawer(self):
        self._agent_drawer = ctk.CTkFrame(
            self._main_shell,
            width=380,
            corner_radius=S.RADIUS_CARD,
            border_width=1,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER,
        )
        self._agent_drawer.pack_propagate(False)

        header = ctk.CTkFrame(self._agent_drawer, fg_color="transparent", height=40)
        header.pack(fill="x", padx=S.SPACE_MD, pady=(S.SPACE_SM, 0))
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="Agent",
            font=S.font_title(S.SUBTITLE),
            text_color=S.TEXT_PRIMARY,
            anchor="w",
        ).pack(side="left")

        subtle_button(
            header,
            "关闭",
            self._toggle_agent_drawer,
            width=56,
            height=28,
        ).pack(side="right")

        self._ollama_tab = OllamaTab(
            self._agent_drawer,
            config_data=self.config_data,
            on_save=lambda: save_config(self.config_data),
            compact=True,
            action_registry=self._agent_actions,
        )
        self._ollama_tab.pack(fill="both", expand=True)

    def _toggle_agent_drawer(self):
        self._set_agent_drawer_visible(not self._agent_drawer_visible)

    def _set_agent_drawer_visible(self, visible: bool):
        self._agent_drawer_visible = visible
        if visible:
            self._agent_drawer.pack(
                side="right", fill="y", padx=(S.SPACE_MD, 0)
            )
            self._agent_btn.configure(text="关闭")
        else:
            self._agent_drawer.pack_forget()
            self._agent_btn.configure(text="Agent")

    # ── Agent 动作 ───────────────────────────────────────

    def _agent_status(self, _params: dict) -> str:
        current = self._tabview.get() or "未知"
        ticket_tab = self._ticket_tab._nb.get()
        sign_state = "运行中" if self._signing else "未运行"
        train_state = self._ticket_tab._12306_status.get()
        damai_state = self._ticket_tab._damai_status.get()
        return (
            f"当前主页面: {current}\n"
            f"当前抢票子页面: {ticket_tab}\n"
            f"贴吧签到: {sign_state}\n"
            f"12306 查票: {train_state}\n"
            f"大麦查票: {damai_state}"
        )

    def _agent_switch_tab(self, params: dict) -> str:
        tab = str(params.get("tab", "")).lower()
        if tab in {"tieba", "贴吧", "贴吧签到"}:
            self._tabview.set("贴吧签到")
            return "已切换到贴吧签到页面。"
        if tab in {"ticket", "抢票", "票务"}:
            self._tabview.set("抢票 (12306 / 大麦)")
            return "已切换到抢票页面。"
        if tab in {"12306", "train", "火车票"}:
            self._tabview.set("抢票 (12306 / 大麦)")
            self._ticket_tab._nb.set("12306 火车票")
            return "已切换到 12306 火车票页面。"
        if tab in {"damai", "大麦", "大麦网"}:
            self._tabview.set("抢票 (12306 / 大麦)")
            self._ticket_tab._nb.set("大麦网")
            return "已切换到大麦网页面。"
        return "没有识别要切换的页面，可用页面: tieba、ticket、12306、damai。"

    def _agent_tieba_sign_all(self, _params: dict) -> str:
        if self._signing:
            return "贴吧签到任务已经在运行。"
        if not self._bduss_var.get().strip():
            return "无法执行一键签到：请先在贴吧签到页面填写 BDUSS。"
        self._tabview.set("贴吧签到")
        self._on_onekey()
        return "已开始贴吧一键签到，执行进度会显示在贴吧签到日志中。"

    def _agent_tieba_sign_normal(self, _params: dict) -> str:
        if self._signing:
            return "贴吧签到任务已经在运行。"
        if not self._bduss_var.get().strip():
            return "无法执行逐个签到：请先在贴吧签到页面填写 BDUSS。"
        self._tabview.set("贴吧签到")
        self._on_sign()
        return "已开始贴吧逐个签到，执行进度会显示在贴吧签到日志中。"

    def _agent_tieba_stop(self, _params: dict) -> str:
        if not self._signing:
            return "当前没有正在运行的贴吧签到任务。"
        self._on_stop()
        return "已请求停止贴吧签到任务。"

    def _agent_ticket_start(self, params: dict) -> str:
        tab = self._ticket_tab
        self._tabview.set("抢票 (12306 / 大麦)")
        tab._nb.set("12306 火车票")
        if tab._12306_worker.is_running():
            return "12306 查票任务已经在运行。"
        if tab._12306_auto_order.get():
            return "为避免误操作，Agent 暂不启动已开启自动下单的 12306 任务。请先关闭自动下单后再试。"

        if params.get("from"):
            tab._12306_from.set(str(params["from"]))
        if params.get("to"):
            tab._12306_to.set(str(params["to"]))
        if params.get("date"):
            tab._12306_date.set(str(params["date"]))
        if params.get("seat"):
            tab._12306_seat.set(str(params["seat"]))

        missing = []
        if not tab._12306_cookie.get().strip():
            missing.append("Cookie")
        if not tab._12306_from.get().strip():
            missing.append("出发站")
        if not tab._12306_to.get().strip():
            missing.append("到达站")
        if not tab._12306_date.get().strip():
            missing.append("出发日期")
        if missing:
            return "无法开始 12306 查票：请先填写 " + " / ".join(missing) + "。"

        tab._on_12306_start()
        return (
            "已开始 12306 查票："
            f"{tab._12306_from.get()} → {tab._12306_to.get()} "
            f"{tab._12306_date.get()}，席别 {tab._12306_seat.get()}。"
        )

    def _agent_ticket_stop(self, _params: dict) -> str:
        self._tabview.set("抢票 (12306 / 大麦)")
        self._ticket_tab._nb.set("12306 火车票")
        if not self._ticket_tab._12306_worker.is_running():
            return "当前没有正在运行的 12306 查票任务。"
        self._ticket_tab._on_12306_stop()
        return "已请求停止 12306 查票任务。"

    def _agent_damai_start(self, params: dict) -> str:
        tab = self._ticket_tab
        self._tabview.set("抢票 (12306 / 大麦)")
        tab._nb.set("大麦网")
        if tab._damai_worker.is_running():
            return "大麦查票任务已经在运行。"

        if params.get("url_or_id"):
            tab._damai_url.set(str(params["url_or_id"]))

        missing = []
        if not tab._damai_cookie.get().strip():
            missing.append("Cookie")
        if not tab._damai_url.get().strip():
            missing.append("演出 URL/ID")
        if missing:
            return "无法开始大麦库存查询：请先填写 " + " / ".join(missing) + "。"

        tab._on_damai_start()
        return f"已开始大麦库存查询：{tab._damai_url.get()}。"

    def _agent_damai_stop(self, _params: dict) -> str:
        self._tabview.set("抢票 (12306 / 大麦)")
        self._ticket_tab._nb.set("大麦网")
        if not self._ticket_tab._damai_worker.is_running():
            return "当前没有正在运行的大麦查票任务。"
        self._ticket_tab._on_damai_stop()
        return "已请求停止大麦查票任务。"

    def _build_tieba_tab(self, parent):
        pad = {"padx": S.SPACE_MD, "pady": S.SPACE_SM}

        # BDUSS
        card = SectionCard(parent, title="BDUSS 设置")
        card.pack(fill="x", **pad)
        body = card.body
        body.columnconfigure(1, weight=1)

        ctk.CTkLabel(
            body, text="BDUSS",
            font=S.font_body(), text_color=S.TEXT_SECONDARY,
        ).grid(row=0, column=0, sticky="w", padx=(0, S.SPACE_MD))
        self._bduss_var = tk.StringVar()
        self._bduss_entry = ctk.CTkEntry(
            body, textvariable=self._bduss_var, show="*",
            height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
        )
        self._bduss_entry.grid(row=0, column=1, sticky="ew", padx=(0, S.SPACE_SM))
        self._toggle_btn = standard_button(
            body, "显示", self._toggle_show, width=64,
        )
        self._toggle_btn.grid(row=0, column=2)

        # 操作按钮
        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(fill="x", **pad)
        self._save_btn = standard_button(
            actions, "保存 BDUSS", self._on_save, width=100
        )
        self._save_btn.pack(side="left", padx=(0, S.SPACE_SM))
        self._sign_btn = accent_button(
            actions, "逐个签到", self._on_sign, width=100,
        )
        self._sign_btn.pack(side="left", padx=(0, S.SPACE_SM))
        self._onekey_btn = accent_button(
            actions, "一键签到", self._on_onekey, width=100,
        )
        self._onekey_btn.pack(side="left", padx=(0, S.SPACE_SM))
        self._stop_btn = danger_button(
            actions, "停止签到", self._on_stop, width=100, state="disabled",
        )
        self._stop_btn.pack(side="left")

        self._status_var = tk.StringVar(value="就绪")
        ctk.CTkLabel(
            actions, textvariable=self._status_var,
            text_color=S.TEXT_SECONDARY, font=S.font_body(),
        ).pack(side="right")

        # 定时任务
        card = SectionCard(parent, title="定时任务")
        card.pack(fill="x", **pad)
        body = card.body

        self._schedule_enabled_var = tk.BooleanVar()
        ctk.CTkCheckBox(
            body, text="启用每日定时签到",
            variable=self._schedule_enabled_var,
            font=S.font_body(),
            text_color=S.TEXT_PRIMARY,
            fg_color=S.accent_pair(),
            hover_color=S.accent_hover_pair(),
            border_color=S.TEXT_TERTIARY,
            checkmark_color=S.TEXT_ON_ACCENT,
            corner_radius=S.RADIUS_INPUT - 1,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            body, text="时间", font=S.font_body(), text_color=S.TEXT_SECONDARY,
        ).grid(row=0, column=1, padx=(S.SPACE_LG, S.SPACE_SM), sticky="e")
        self._hour_var = tk.StringVar(value="08")
        self._minute_var = tk.StringVar(value="00")
        self._make_time_entry(body, self._hour_var).grid(row=0, column=2)
        ctk.CTkLabel(
            body, text=":", font=S.font_body(14, "bold"), text_color=S.TEXT_PRIMARY,
        ).grid(row=0, column=3, padx=2)
        self._make_time_entry(body, self._minute_var).grid(row=0, column=4)

        accent_button(
            body, "保存设置", self._on_schedule_save, width=100, height=30,
        ).grid(row=0, column=5, padx=(S.SPACE_LG, 0))

        ctk.CTkLabel(
            body, text="签到方式", font=S.font_body(), text_color=S.TEXT_SECONDARY,
        ).grid(row=1, column=0, sticky="w", pady=(S.SPACE_MD, 0))
        self._schedule_mode_var = tk.StringVar(value="onekey")
        ctk.CTkRadioButton(
            body, text="一键 (失败回退逐个)",
            variable=self._schedule_mode_var, value="onekey",
            font=S.font_body(), text_color=S.TEXT_PRIMARY,
            fg_color=S.accent_pair(),
            hover_color=S.accent_hover_pair(),
            border_color=S.TEXT_TERTIARY,
        ).grid(row=1, column=1, columnspan=3, sticky="w", pady=(S.SPACE_MD, 0))
        ctk.CTkRadioButton(
            body, text="逐个签到",
            variable=self._schedule_mode_var, value="normal",
            font=S.font_body(), text_color=S.TEXT_PRIMARY,
            fg_color=S.accent_pair(),
            hover_color=S.accent_hover_pair(),
            border_color=S.TEXT_TERTIARY,
        ).grid(row=1, column=4, columnspan=2, sticky="w", pady=(S.SPACE_MD, 0))

        self._schedule_info_var = tk.StringVar()
        ctk.CTkLabel(
            body, textvariable=self._schedule_info_var,
            text_color=S.INFO, font=S.font_body(),
        ).grid(row=2, column=0, columnspan=6, sticky="w", pady=(S.SPACE_SM, 0))

        # 开机自启
        card = SectionCard(parent, title="开机自启")
        card.pack(fill="x", **pad)
        body = card.body

        self._startup_enabled_var = tk.BooleanVar()
        ctk.CTkCheckBox(
            body, text="开机自动启动", variable=self._startup_enabled_var,
            command=self._refresh_startup_info,
            font=S.font_body(), text_color=S.TEXT_PRIMARY,
            fg_color=S.accent_pair(),
            hover_color=S.accent_hover_pair(),
            border_color=S.TEXT_TERTIARY,
            corner_radius=S.RADIUS_INPUT - 1,
        ).grid(row=0, column=0, sticky="w")
        self._startup_minimize_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            body, text="自启后缩小到托盘（无感启动）",
            variable=self._startup_minimize_var,
            command=self._refresh_startup_info,
            font=S.font_body(), text_color=S.TEXT_PRIMARY,
            fg_color=S.accent_pair(),
            hover_color=S.accent_hover_pair(),
            border_color=S.TEXT_TERTIARY,
            corner_radius=S.RADIUS_INPUT - 1,
        ).grid(row=0, column=1, padx=(S.SPACE_LG, 0), sticky="w")

        accent_button(
            body, "保存自启设置", self._on_startup_save, width=120, height=30,
        ).grid(row=0, column=2, padx=(S.SPACE_LG, 0))

        self._startup_info_var = tk.StringVar()
        ctk.CTkLabel(
            body, textvariable=self._startup_info_var,
            text_color=S.INFO, font=S.font_body(),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(S.SPACE_SM, 0))

        # 路径条
        path_bar = ctk.CTkFrame(parent, fg_color="transparent")
        path_bar.pack(fill="x", **pad)
        ctk.CTkLabel(
            path_bar,
            text=f"配置: {CONFIG_FILE.name}   ·   日志: {LOG_FILE.name}",
            text_color=S.TEXT_TERTIARY, font=S.font_body(),
        ).pack(side="left")
        subtle_button(
            path_bar, "打开目录", self._open_config_dir, width=80,
        ).pack(side="right")

        # 进度条
        self._progress = ProgressWithLabel(parent, height=6)
        self._progress.pack(fill="x", **pad)

        # 日志
        log_card = SectionCard(parent, title="签到日志")
        log_card.pack(fill="both", expand=True, **pad)
        self._log_view = LogView(log_card.body, height=240, show_clear_btn=True)
        self._log_view.pack(fill="both", expand=True)

    def _make_time_entry(self, parent, var: tk.StringVar) -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent, textvariable=var, width=46, height=30,
            justify="center",
            corner_radius=S.RADIUS_INPUT,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
        )

    # ── 主题切换 ─────────────────────────────────────────

    THEME_CYCLE = ("system", "light", "dark")
    THEME_ICONS = {"system": "\U0001F5A5", "light": "\u2600", "dark": "\u263E"}

    def _theme_icon(self, mode: str) -> str:
        return self.THEME_ICONS.get(mode, self.THEME_ICONS["system"])

    def _cycle_theme(self):
        current = self._theme_var.get()
        try:
            idx = self.THEME_CYCLE.index(current)
        except ValueError:
            idx = -1
        next_mode = self.THEME_CYCLE[(idx + 1) % len(self.THEME_CYCLE)]
        self._theme_var.set(next_mode)
        self._on_theme_change(next_mode)

    def _on_theme_change(self, value: str):
        ctk.set_appearance_mode(value)
        self.config_data["ui_theme"] = value
        save_config(self.config_data)
        S.apply_window_chrome(self)
        try:
            self._theme_btn.configure(text=self._theme_icon(value))
        except (AttributeError, tk.TclError):
            pass
        try:
            self._tabview.refresh_theme()
        except AttributeError:
            pass
        try:
            self._ticket_tab.refresh_theme()
        except (AttributeError, tk.TclError):
            pass
        try:
            self._log_view.refresh_theme()
        except AttributeError:
            pass

    # ── 打开配置目录 ──────────────────────────────────────

    def _open_config_dir(self):
        try:
            os.startfile(str(CONFIG_FILE.parent))
        except OSError as e:
            messagebox.showerror("无法打开目录", str(e))

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
            mode = "一键签到" if self._schedule_mode_var.get() == "onekey" else "逐个签到"
            self._schedule_info_var.set(f"已启用 — 每天 {t} 自动执行【{mode}】")
        else:
            self._schedule_info_var.set("未启用")

    def _refresh_startup_info(self):
        if os.name != "nt":
            self._startup_info_var.set("当前系统不支持 Windows 开机启动项")
            return
        if self._startup_enabled_var.get():
            mode = (
                "启动后自动缩小到托盘"
                if self._startup_minimize_var.get()
                else "启动后显示窗口"
            )
            self._startup_info_var.set(f"已启用 — {mode}")
        else:
            self._startup_info_var.set("未启用")

    def _log_startup_status(self):
        enabled = is_startup_enabled()
        mode = (
            "缩小到托盘"
            if self.config_data.get("startup_minimize_to_tray", True)
            else "显示窗口"
        )
        arg_mode = "，本次按自启参数启动" if self._start_minimized else ""
        self._log(
            f"开机自启: {'已启用' if enabled else '未启用'}，自启后{mode}{arg_mode}",
            "info",
        )

    # ── BDUSS 显示/隐藏 ─────────────────────────────────

    def _toggle_show(self):
        self._show_bduss = not self._show_bduss
        self._bduss_entry.configure(show="" if self._show_bduss else "*")
        self._toggle_btn.configure(text="隐藏" if self._show_bduss else "显示")

    # ── 日志 ─────────────────────────────────────────────

    def _log(self, text: str, tag: str = "info"):
        self._log_view.log(text, tag if tag else "info")
        clean = text.strip()
        if clean:
            logger.info(clean)

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
            try:
                self._current_session.close()
            except Exception:
                pass
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
        try:
            int(self._hour_var.get())
            int(self._minute_var.get())
        except ValueError:
            messagebox.showwarning("提示", "时/分 必须是数字")
            return
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

    # ── 签到入口 ─────────────────────────────────────────

    def _start_sign_thread(self, target_name: str, action: str):
        bduss = self._bduss_var.get().strip()
        if not bduss:
            messagebox.showwarning("提示", "请先输入 BDUSS")
            return
        self.config_data["bduss"] = bduss
        self._signing = True
        self._set_busy(True)
        self._progress.reset()
        self._log(f"──── 手动触发：{action} ────", "info")
        threading.Thread(
            target=getattr(self._sign_worker, target_name), daemon=True
        ).start()

    def _on_sign(self):
        self._start_sign_thread("run_normal", "逐个签到")

    def _on_onekey(self):
        self._start_sign_thread("run_onekey", "一键签到")

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
                self._ui(self._progress.reset)

                mode = self.config_data.get("schedule_mode", "onekey")
                self._ui(
                    self._log,
                    f"──── 定时触发：{now.strftime('%H:%M:%S')} "
                    f"{'一键签到' if mode == 'onekey' else '逐个签到'} ────",
                    "info",
                )
                try:
                    self._sign_worker.run_scheduled(mode)
                except Exception as e:
                    logger.error(f"定时任务异常: {e}\n{traceback.format_exc()}")
                    self._ui(self._log, f"[定时任务异常] {e}", "fail")
                    self._ui(self._finish)

    # ── 线程安全的 UI 更新 ───────────────────────────────

    def _ui(self, func, *args, **kwargs):
        if kwargs:
            self.after(0, lambda f=func, a=args, k=kwargs: f(*a, **k))
        else:
            self.after(0, func, *args)

    def _set_progress(self, value):
        self._progress.set_value(int(value))

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
        self.after(0, self._on_close)

    # ── 关闭请求（X 按钮）─────────────────────────────────

    def _on_close_request(self):
        """窗口 X 按钮触发：根据 close_action 配置决定行为或弹窗询问。"""
        action = self.config_data.get("close_action", "ask")
        if action == "minimize":
            self._minimize_to_tray()
            return
        if action == "quit":
            self._on_close()
            return
        self._show_close_dialog()

    def _show_close_dialog(self):
        if self._close_dialog is not None:
            try:
                self._close_dialog.lift()
                self._close_dialog.focus_force()
                return
            except tk.TclError:
                self._close_dialog = None

        dlg = ctk.CTkToplevel(self)
        self._close_dialog = dlg
        dlg.title("关闭程序")
        dlg.transient(self)
        dlg.resizable(False, False)
        dlg.configure(fg_color=S.WIN_BG)

        w, h = 380, 200
        try:
            x = self.winfo_rootx() + (self.winfo_width() - w) // 2
            y = self.winfo_rooty() + (self.winfo_height() - h) // 2
        except tk.TclError:
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 2
        dlg.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")

        ctk.CTkLabel(
            dlg, text="你希望如何关闭程序？",
            font=S.font_title(S.SUBTITLE),
            text_color=S.TEXT_PRIMARY,
        ).pack(pady=(S.SPACE_LG, S.SPACE_XS))
        ctk.CTkLabel(
            dlg, text="缩到托盘可继续在后台执行定时签到。",
            font=S.font_body(), text_color=S.TEXT_SECONDARY,
        ).pack(pady=(0, S.SPACE_MD))

        remember_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            dlg, text="记住选择，下次不再询问",
            variable=remember_var,
            font=S.font_body(), text_color=S.TEXT_PRIMARY,
            fg_color=S.accent_pair(), hover_color=S.accent_hover_pair(),
            border_color=S.TEXT_TERTIARY,
            checkmark_color=S.TEXT_ON_ACCENT,
            corner_radius=S.RADIUS_INPUT - 1,
        ).pack(pady=(0, S.SPACE_MD))

        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(pady=(0, S.SPACE_LG))

        def _do(action: str):
            if action != "cancel" and remember_var.get():
                self.config_data["close_action"] = action
                save_config(self.config_data)
            try:
                dlg.grab_release()
                dlg.destroy()
            except tk.TclError:
                pass
            self._close_dialog = None
            if action == "minimize":
                self._minimize_to_tray()
            elif action == "quit":
                self._on_close()

        standard_button(
            btns, "缩到托盘", lambda: _do("minimize"), width=100,
        ).pack(side="left", padx=S.SPACE_XS)
        danger_button(
            btns, "退出程序", lambda: _do("quit"), width=100,
        ).pack(side="left", padx=S.SPACE_XS)
        subtle_button(
            btns, "取消", lambda: _do("cancel"), width=80,
        ).pack(side="left", padx=S.SPACE_XS)

        dlg.protocol("WM_DELETE_WINDOW", lambda: _do("cancel"))
        dlg.after(50, lambda: (dlg.grab_set(), dlg.focus_force()))

    # ── 退出清理 ─────────────────────────────────────────

    def _on_close(self):
        self._scheduler_stop.set()
        self._signing = False

        if self._current_session is not None:
            try:
                self._current_session.close()
            except Exception:
                pass
            self._current_session = None

        try:
            browser = getattr(self._ticket_tab, "_browser", None)
            if browser is not None:
                browser.close()
        except Exception:
            pass

        try:
            self._tray.stop()
        except Exception:
            pass

        try:
            self.destroy()
        except tk.TclError:
            pass

        # 兜底：强制退出，避免残留 daemon=False 的第三方线程或子进程拖住 Python
        os._exit(0)


def main():
    app = App(start_minimized=START_MINIMIZED_ARG in sys.argv[1:])
    app.mainloop()


if __name__ == "__main__":
    main()
