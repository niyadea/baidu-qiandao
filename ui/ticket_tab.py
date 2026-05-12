"""抢票页签：12306 / 大麦 / 说明 三个子页（Win11 Fluent Design 版）。"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from core import (
    BrowserSession,
    damai,
    detect_chrome_path,
    make_browser_session,
    ticket12306,
    ticket12306_order,
)

from . import styling as S
from .ticket_worker import DamaiWorker, Ticket12306Worker
from .widgets import (
    IntSpinBox,
    LogView,
    PivotTabs,
    SectionCard,
    SelectableList,
    accent_button,
    danger_button,
    standard_button,
)

FEASIBILITY_TEXT = (
    "工具组合策略\n"
    "─────────────────────────────────────────────\n"
    "• 12306：「Cookie 协议查票（快）」+「DrissionPage 浏览器半自动购票（稳）」。\n"
    "  协议层秒级轮询余票，命中后一键打开浏览器跳到购票页并自动填好行程，\n"
    "  你只需点查询、选车次、过滑块、提交。比纯协议自动下单封号风险低很多。\n\n"
    "• 大麦：人机校验极强（IP+设备指纹+行为校验），仅做「Cookie 查库存」+\n"
    "  「浏览器打开演出页」辅助。命中库存后由你在浏览器手动下单。\n\n"
    "免责声明\n"
    "─────────────────────────────────────────────\n"
    "• 本工具仅供个人使用，禁止用于黄牛/牟利；\n"
    "• 所有 Cookie 仅本地保存到 config.json，不会上传任何外部服务器；\n"
    "• 自动下单违反 12306 TOS，触发风控/封号风险自负；\n"
    "• 浏览器登录态保存在程序目录的 chrome_profile/，与系统主 Chrome 隔离。"
)

COOKIE_HELP_12306 = """12306 Cookie 获取步骤（官方账号登录后导出）

────────────────────────────────────────
为什么要 Cookie？
  12306 的余票查询、候补、提交订单都需要带 cookie。账号密码 + 滑块 + 短信
  在程序里走自动化极易被风控封号，所以这里只让你在浏览器登录后，把登录态
  cookie 复制过来；本工具仅用它做「查票/轮询」，不会自动下单。

──── 详细步骤 ────────────────────────────
1. 用 Chrome / Edge / Firefox 打开：
       https://kyfw.12306.cn/otn/resources/login.html

2. 输入账号密码 + 完成滑块/短信验证，登录成功，确认右上角显示你的姓名。

3. 不要关闭浏览器，按 F12 打开「开发者工具」。

4. 切换到「网络 / Network」标签页，勾选上方「保留日志 / Preserve log」。

5. 在地址栏输入：
       https://kyfw.12306.cn/otn/index/initMy12306Api
   按回车（或在 Network 列表里找到任意一个 12306.cn 域名下的请求）。

6. 在 Network 列表点击该请求，右侧切换到「标头 / Headers」。

7. 滚到「请求标头 / Request Headers」段，找到一行：
       cookie: JSESSIONID=xxx; BIGipServer~xxx; tk=xxx; _jc_save_xxx=...
   把整行 cookie 的值（冒号后面的全部文本）复制下来。
   ※ Chrome 可在该行右键 →「复制值 / Copy value」。

8. 粘贴到下方「Cookie」输入框，点「校验 Cookie」按钮，看到
   「✓ Cookie 有效，姓名：XXX」即配置成功。

──── 注意 ───────────────────────────────
  • Cookie 通常 30 分钟到几小时内有效，过期后请重新获取；登录设备/IP
    频繁变动会触发风控。
  • 切勿把你的 cookie 发给任何人或上传到公共仓库，等同账号密码。
  • 本程序只在本地保存到 config.json（与 BDUSS 同目录），不会上传。
"""

COOKIE_HELP_DAMAI = """大麦网 Cookie 获取步骤（淘宝账号登录后导出）

────────────────────────────────────────
为什么要 Cookie？
  大麦的演出详情、票档库存、下单接口都依赖淘系 cookie（cookie2 / _tb_token_
  / sgcookie / _m_h5_tk 等）。账号密码自动登录会被反爬阻断，因此只让你在
  浏览器登录后，把登录态 cookie 拷贝过来；本工具仅做「查库存/轮询」。

──── 详细步骤 ────────────────────────────
1. 用 Chrome / Edge 打开：
       https://www.damai.cn
   右上角点「登录」，使用「淘宝账号」扫码或密码登录，确认头像出现。

2. 不要关闭浏览器，按 F12 打开「开发者工具」。

3. 切到「应用 / Application」标签 →「存储 / Storage」→「Cookies」
   →「https://www.damai.cn」。

4. 一次性复制方法（推荐）：
   切到「网络 / Network」标签 → 刷新页面（F5）→ 在请求列表点最上方的
   document 请求（通常就是 www.damai.cn）→「标头 / Headers」→
   「请求标头 / Request Headers」里找到「cookie:」那一整行，复制整行值。

5. 关键 cookie 名（如果上面整行没有，请人工拼接）：
       cookie2 _tb_token_ sgcookie unb _m_h5_tk _m_h5_tk_enc t cna
   格式：name1=value1; name2=value2; ...

6. 粘贴到下方「Cookie」输入框，点「校验 Cookie」按钮，看到
   「✓ Cookie 有效，昵称：XXX」即配置成功。

──── 注意 ───────────────────────────────
  • _m_h5_tk 是 mtop 接口签名 token，每次刷新页面会变；如果校验失败，
    刷新一下浏览器再复制。
  • 大麦/淘宝对账号风控极严，不要在多 IP/多设备频繁切换；不要同时跑
    多个抢票工具。
  • Cookie 等同账号密码，切勿外传或提交到代码仓库。
"""


# ── 常用样式辅助 ────────────────────────────────────────


def _entry(parent, var, **kw) -> ctk.CTkEntry:
    defaults = dict(
        textvariable=var,
        height=S.INPUT_HEIGHT,
        corner_radius=S.RADIUS_INPUT,
        border_color=S.LAYER_BORDER,
        fg_color=S.LAYER_ALT,
        text_color=S.TEXT_PRIMARY,
        font=S.font_body(),
    )
    defaults.update(kw)
    return ctk.CTkEntry(parent, **defaults)


def _label(parent, text, *, secondary=False, **kw) -> ctk.CTkLabel:
    color = S.TEXT_SECONDARY if secondary else S.TEXT_PRIMARY
    defaults = dict(text=text, font=S.font_body(), text_color=color)
    defaults.update(kw)
    return ctk.CTkLabel(parent, **defaults)


def _checkbox(parent, text, variable, **kw) -> ctk.CTkCheckBox:
    defaults = dict(
        text=text, variable=variable,
        font=S.font_body(),
        text_color=S.TEXT_PRIMARY,
        fg_color=S.accent_pair(),
        hover_color=S.accent_hover_pair(),
        border_color=S.TEXT_TERTIARY,
        checkmark_color=S.TEXT_ON_ACCENT,
        corner_radius=S.RADIUS_INPUT - 1,
    )
    defaults.update(kw)
    return ctk.CTkCheckBox(parent, **defaults)


def _radio(parent, text, variable, value, **kw) -> ctk.CTkRadioButton:
    defaults = dict(
        text=text, variable=variable, value=value,
        font=S.font_body(),
        text_color=S.TEXT_PRIMARY,
        fg_color=S.accent_pair(),
        hover_color=S.accent_hover_pair(),
        border_color=S.TEXT_TERTIARY,
    )
    defaults.update(kw)
    return ctk.CTkRadioButton(parent, **defaults)


class TicketTab(ctk.CTkFrame):
    """抢票主页签：内含 12306 / 大麦网 / 说明 三个子页签。"""

    def __init__(
        self,
        parent,
        config_data: dict | None = None,
        on_save: Callable[[], None] | None = None,
    ):
        super().__init__(parent, fg_color="transparent")
        self._config = config_data if config_data is not None else {}
        self._on_save = on_save or (lambda: None)
        self._12306_worker = Ticket12306Worker()
        self._damai_worker = DamaiWorker()
        self._browser: BrowserSession | None = None

        self._build()
        self._bind_persistence()

    def _build(self):
        self._nb = PivotTabs(self)
        self._nb.pack(fill="both", expand=True)

        tab12306 = self._nb.add("12306 火车票")
        tab_damai = self._nb.add("大麦网")
        tab_info = self._nb.add("说明")

        self._build_12306(tab12306)
        self._build_damai(tab_damai)
        self._build_info(tab_info)

    def _bind_persistence(self):
        def _save_bool(key, var):
            self._config[key] = bool(var.get())
            self._on_save()

        def _save_int(key, var, default):
            try:
                self._config[key] = max(1, int(var.get()))
            except (TypeError, tk.TclError):
                self._config[key] = default
            self._on_save()

        self._12306_auto_order.trace_add(
            "write",
            lambda *_: _save_bool("12306_auto_order_enabled", self._12306_auto_order),
        )
        self._12306_dry_run.trace_add(
            "write",
            lambda *_: _save_bool("12306_auto_order_dry_run", self._12306_dry_run),
        )
        self._12306_interval.trace_add(
            "write",
            lambda *_: _save_int("12306_query_interval", self._12306_interval, 3),
        )
        self._12306_pax_list.bind_select(self._on_12306_pax_select)

    def refresh_theme(self):
        self._12306_pax_list.refresh_theme()
        try:
            self._12306_logview.refresh_theme()
            self._damai_logview.refresh_theme()
        except AttributeError:
            pass
        try:
            self._nb.refresh_theme()
        except AttributeError:
            pass

    # ── 12306 子页 ──────────────────────────────────────

    def _build_12306(self, parent):
        pad = {"padx": S.SPACE_MD, "pady": S.SPACE_SM}

        # Cookie
        card = SectionCard(parent, title="12306 登录 Cookie")
        card.pack(fill="x", **pad)
        body = card.body
        body.columnconfigure(1, weight=1)

        _label(body, "Cookie", secondary=True).grid(
            row=0, column=0, sticky="w", padx=(0, S.SPACE_MD)
        )
        self._12306_cookie = tk.StringVar()
        _entry(body, self._12306_cookie, show="*").grid(
            row=0, column=1, sticky="ew", padx=(0, S.SPACE_SM)
        )
        self._12306_validate_btn = accent_button(
            body, "校验 Cookie", self._on_12306_validate, width=110,
        )
        self._12306_validate_btn.grid(row=0, column=2, padx=(0, S.SPACE_SM))
        standard_button(
            body, "?", lambda: self._show_cookie_help("12306"), width=32,
        ).grid(row=0, column=3)

        # 行程
        card = SectionCard(parent, title="行程")
        card.pack(fill="x", **pad)
        body = card.body

        _label(body, "出发站", secondary=True).grid(
            row=0, column=0, sticky="w", padx=(0, S.SPACE_SM), pady=2
        )
        self._12306_from = tk.StringVar()
        _entry(body, self._12306_from, width=170).grid(
            row=0, column=1, sticky="w", padx=(0, S.SPACE_LG), pady=2
        )
        _label(body, "到达站", secondary=True).grid(
            row=0, column=2, sticky="w", padx=(0, S.SPACE_SM), pady=2
        )
        self._12306_to = tk.StringVar()
        _entry(body, self._12306_to, width=170).grid(
            row=0, column=3, sticky="w", pady=2
        )

        _label(body, "出发日期", secondary=True).grid(
            row=1, column=0, sticky="w", padx=(0, S.SPACE_SM), pady=(S.SPACE_SM, 2)
        )
        self._12306_date = tk.StringVar()
        _entry(body, self._12306_date, width=170).grid(
            row=1, column=1, sticky="w", padx=(0, S.SPACE_LG), pady=(S.SPACE_SM, 2)
        )
        _label(
            body, "格式: 2026-05-12", secondary=True,
        ).grid(row=1, column=2, columnspan=2, sticky="w", pady=(S.SPACE_SM, 2))

        # 车次/席别
        card = SectionCard(parent, title="车次 / 席别")
        card.pack(fill="x", **pad)
        body = card.body

        _label(body, "车次类型", secondary=True).grid(
            row=0, column=0, sticky="w", pady=2
        )
        self._12306_types: dict[str, tk.BooleanVar] = {}
        for i, t in enumerate(["G/C", "D", "Z", "T", "K", "其他"]):
            var = tk.BooleanVar(value=t in ("G/C", "D"))
            self._12306_types[t] = var
            _checkbox(
                body, t, var, checkbox_width=18, checkbox_height=18,
            ).grid(row=0, column=1 + i, padx=S.SPACE_SM, pady=2, sticky="w")

        _label(body, "席别", secondary=True).grid(
            row=1, column=0, sticky="w", pady=(S.SPACE_SM, 0)
        )
        self._12306_seat = tk.StringVar(value="二等座")
        ctk.CTkOptionMenu(
            body, variable=self._12306_seat,
            values=[
                "商务座", "特等座", "一等座", "二等座",
                "高级软卧", "软卧", "动卧", "硬卧",
                "软座", "硬座", "无座",
            ],
            width=160, height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            fg_color=S.LAYER_ALT,
            button_color=S.accent_pair(),
            button_hover_color=S.accent_hover_pair(),
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
        ).grid(row=1, column=1, columnspan=4, sticky="w", pady=(S.SPACE_SM, 0))

        # 自动下单
        card = SectionCard(parent, title="自动下单（违反 12306 TOS，封号风险自负）")
        card.pack(fill="x", **pad)
        body = card.body

        self._12306_auto_order = tk.BooleanVar(
            value=bool(self._config.get("12306_auto_order_enabled", False))
        )
        _checkbox(body, "启用自动下单", self._12306_auto_order).grid(
            row=0, column=0, sticky="w"
        )
        self._12306_dry_run = tk.BooleanVar(
            value=bool(self._config.get("12306_auto_order_dry_run", True))
        )
        _checkbox(
            body, "Dry-run 测试模式（推荐首次开启）", self._12306_dry_run,
        ).grid(row=0, column=1, padx=(S.SPACE_LG, 0), sticky="w")

        standard_button(
            body, "加载乘客", self._on_12306_load_passengers, width=100, height=30,
        ).grid(row=1, column=0, pady=(S.SPACE_MD, 0), sticky="w")
        self._12306_pax_status = tk.StringVar(value="未加载（先填 Cookie 再点加载）")
        _label(
            body, "", secondary=True, textvariable=self._12306_pax_status,
        ).grid(row=1, column=1, padx=(S.SPACE_LG, 0), pady=(S.SPACE_MD, 0), sticky="w")

        _label(
            body, "选乘客（按住 Ctrl 多选，最多 2 人）", secondary=True,
        ).grid(row=2, column=0, columnspan=2, pady=(S.SPACE_MD, 0), sticky="w")
        self._12306_pax_list = SelectableList(body, height=4)
        self._12306_pax_list.grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(S.SPACE_XS, 0)
        )
        self._12306_pax_data: list[dict] = []
        body.columnconfigure(1, weight=1)

        # 抢票时间
        card = SectionCard(parent, title="抢票时间")
        card.pack(fill="x", **pad)
        body = card.body

        self._12306_when_mode = tk.StringVar(value="now")
        _radio(body, "立即开抢", self._12306_when_mode, "now").grid(
            row=0, column=0, sticky="w"
        )
        _radio(body, "定时开抢", self._12306_when_mode, "timed").grid(
            row=0, column=1, padx=(S.SPACE_LG, S.SPACE_SM), sticky="w"
        )
        self._12306_when = tk.StringVar(value="13:00:00")
        _entry(body, self._12306_when, width=120).grid(
            row=0, column=2, sticky="w"
        )
        _label(body, "HH:MM:SS", secondary=True).grid(
            row=0, column=3, padx=(S.SPACE_SM, 0), sticky="w"
        )

        _label(body, "查询间隔", secondary=True).grid(
            row=1, column=0, sticky="w", pady=(S.SPACE_MD, 0)
        )
        self._12306_interval = tk.IntVar(
            value=max(1, int(self._config.get("12306_query_interval", 3)))
        )
        IntSpinBox(
            body, from_=1, to=60, textvariable=self._12306_interval, width=120,
        ).grid(row=1, column=1, sticky="w", pady=(S.SPACE_MD, 0))
        _label(body, "秒/次（最低 1s）", secondary=True).grid(
            row=1, column=2, columnspan=2, sticky="w", pady=(S.SPACE_MD, 0)
        )

        # 操作按钮
        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(fill="x", **pad)

        self._12306_start_btn = accent_button(
            actions, "开始查票", self._on_12306_start, width=110,
        )
        self._12306_start_btn.pack(side="left", padx=(0, S.SPACE_SM))
        self._12306_stop_btn = danger_button(
            actions, "停止", self._on_12306_stop, width=80, state="disabled",
        )
        self._12306_stop_btn.pack(side="left", padx=(0, S.SPACE_LG))
        self._12306_browser_btn = accent_button(
            actions, "浏览器购票", self._on_12306_browser_buy, width=110,
        )
        self._12306_browser_btn.pack(side="left", padx=(0, S.SPACE_SM))
        self._12306_login_btn = standard_button(
            actions, "浏览器登录", self._on_12306_browser_login, width=100,
        )
        self._12306_login_btn.pack(side="left")

        self._12306_status = tk.StringVar(value="未开始")
        _label(actions, "", secondary=True, textvariable=self._12306_status).pack(
            side="right"
        )

        # 日志
        card = SectionCard(parent, title="状态日志")
        card.pack(fill="both", expand=True, **pad)
        self._12306_logview = LogView(card.body, height=160, show_clear_btn=True)
        self._12306_logview.pack(fill="both", expand=True)

    # ── 大麦网子页 ───────────────────────────────────────

    def _build_damai(self, parent):
        pad = {"padx": S.SPACE_MD, "pady": S.SPACE_SM}

        card = SectionCard(parent, title="大麦登录 Cookie")
        card.pack(fill="x", **pad)
        body = card.body
        body.columnconfigure(1, weight=1)

        _label(body, "Cookie", secondary=True).grid(
            row=0, column=0, sticky="w", padx=(0, S.SPACE_MD)
        )
        self._damai_cookie = tk.StringVar()
        _entry(body, self._damai_cookie, show="*").grid(
            row=0, column=1, sticky="ew", padx=(0, S.SPACE_SM)
        )
        self._damai_validate_btn = accent_button(
            body, "校验 Cookie", self._on_damai_validate, width=110,
        )
        self._damai_validate_btn.grid(row=0, column=2, padx=(0, S.SPACE_SM))
        standard_button(
            body, "?", lambda: self._show_cookie_help("damai"), width=32,
        ).grid(row=0, column=3)

        card = SectionCard(parent, title="演出信息")
        card.pack(fill="x", **pad)
        body = card.body
        body.columnconfigure(1, weight=1)

        _label(body, "演出 URL / ID", secondary=True).grid(
            row=0, column=0, sticky="w", padx=(0, S.SPACE_SM), pady=2
        )
        self._damai_url = tk.StringVar()
        _entry(body, self._damai_url).grid(
            row=0, column=1, columnspan=3, sticky="ew", pady=2
        )

        _label(body, "场次", secondary=True).grid(
            row=1, column=0, sticky="w", padx=(0, S.SPACE_SM), pady=2
        )
        self._damai_session = tk.StringVar()
        _entry(body, self._damai_session, width=200).grid(
            row=1, column=1, sticky="w", pady=2
        )
        _label(body, "票档", secondary=True).grid(
            row=1, column=2, sticky="w", padx=(S.SPACE_LG, S.SPACE_SM), pady=2
        )
        self._damai_price = tk.StringVar()
        _entry(body, self._damai_price, width=160).grid(
            row=1, column=3, sticky="w", pady=2
        )

        _label(body, "数量", secondary=True).grid(
            row=2, column=0, sticky="w", padx=(0, S.SPACE_SM), pady=2
        )
        self._damai_qty = tk.IntVar(value=1)
        IntSpinBox(
            body, from_=1, to=4, textvariable=self._damai_qty, width=120,
        ).grid(row=2, column=1, sticky="w", pady=2)
        _label(body, "观演人", secondary=True).grid(
            row=2, column=2, sticky="w", padx=(S.SPACE_LG, S.SPACE_SM), pady=2
        )
        self._damai_viewer = tk.StringVar()
        _entry(body, self._damai_viewer, width=160).grid(
            row=2, column=3, sticky="w", pady=2
        )

        card = SectionCard(parent, title="查票策略")
        card.pack(fill="x", **pad)
        body = card.body

        self._damai_when_mode = tk.StringVar(value="now")
        _radio(body, "立即查询", self._damai_when_mode, "now").grid(
            row=0, column=0, sticky="w"
        )
        _radio(body, "定时开始", self._damai_when_mode, "timed").grid(
            row=0, column=1, padx=(S.SPACE_LG, S.SPACE_SM), sticky="w"
        )
        self._damai_when = tk.StringVar(value="20:00:00")
        _entry(body, self._damai_when, width=120).grid(
            row=0, column=2, sticky="w"
        )
        _label(body, "HH:MM:SS", secondary=True).grid(
            row=0, column=3, padx=(S.SPACE_SM, 0), sticky="w"
        )

        _label(body, "轮询间隔", secondary=True).grid(
            row=1, column=0, sticky="w", pady=(S.SPACE_MD, 0)
        )
        self._damai_interval = tk.IntVar(value=2)
        IntSpinBox(
            body, from_=1, to=30, textvariable=self._damai_interval, width=120,
        ).grid(row=1, column=1, sticky="w", pady=(S.SPACE_MD, 0))
        _label(
            body, "秒/次（库存出现时弹窗提醒，不会自动下单）", secondary=True,
        ).grid(row=1, column=2, columnspan=2, sticky="w", pady=(S.SPACE_MD, 0))

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(fill="x", **pad)
        self._damai_start_btn = accent_button(
            actions, "开始查票", self._on_damai_start, width=110,
        )
        self._damai_start_btn.pack(side="left", padx=(0, S.SPACE_SM))
        self._damai_stop_btn = danger_button(
            actions, "停止", self._on_damai_stop, width=80, state="disabled",
        )
        self._damai_stop_btn.pack(side="left", padx=(0, S.SPACE_LG))
        accent_button(
            actions, "浏览器打开", self._on_damai_browser_open, width=110,
        ).pack(side="left")
        self._damai_status = tk.StringVar(value="未开始")
        _label(actions, "", secondary=True, textvariable=self._damai_status).pack(
            side="right"
        )

        card = SectionCard(parent, title="状态日志")
        card.pack(fill="both", expand=True, **pad)
        self._damai_logview = LogView(card.body, height=160, show_clear_btn=True)
        self._damai_logview.pack(fill="both", expand=True)

    # ── 说明子页 ─────────────────────────────────────────

    def _build_info(self, parent):
        text = ctk.CTkTextbox(
            parent, wrap="word",
            font=S.font_body(13),
            corner_radius=S.RADIUS_CARD,
            border_width=1,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER,
            text_color=S.TEXT_PRIMARY,
        )
        text.pack(fill="both", expand=True, padx=S.SPACE_MD, pady=S.SPACE_SM)
        text.insert("1.0", FEASIBILITY_TEXT)
        text.configure(state="disabled")

    # ── Cookie 帮助对话框 ───────────────────────────────

    def _show_cookie_help(self, site: str):
        title = "12306 Cookie 获取步骤" if site == "12306" else "大麦 Cookie 获取步骤"
        content = COOKIE_HELP_12306 if site == "12306" else COOKIE_HELP_DAMAI

        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("780x620")
        win.transient(self.winfo_toplevel())
        win.configure(fg_color=S.WIN_BG)

        try:
            S.apply_window_chrome(win)
        except Exception:
            pass

        btn_bar = ctk.CTkFrame(win, fg_color="transparent")
        btn_bar.pack(side="bottom", fill="x", padx=S.SPACE_LG, pady=S.SPACE_LG)

        def _copy_all():
            self.clipboard_clear()
            self.clipboard_append(content)

        standard_button(btn_bar, "关闭", win.destroy, width=80).pack(side="right")
        accent_button(btn_bar, "复制全文", _copy_all, width=100).pack(
            side="right", padx=(0, S.SPACE_SM)
        )

        text = ctk.CTkTextbox(
            win, wrap="word", font=S.font_body(12),
            corner_radius=S.RADIUS_CARD,
            border_width=1,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER,
            text_color=S.TEXT_PRIMARY,
        )
        text.pack(fill="both", expand=True, padx=S.SPACE_LG, pady=(S.SPACE_LG, 0))
        text.insert("1.0", content)
        text.configure(state="disabled")

    # ── 日志辅助 ────────────────────────────────────────

    def _log_12306(self, text: str, tag: str = "info"):
        self._12306_logview.log(text, tag)

    def _log_damai(self, text: str, tag: str = "info"):
        self._damai_logview.log(text, tag)

    def _ui(self, fn, *args, **kwargs):
        self.after(0, lambda: fn(*args, **kwargs))

    # ── 12306 回调 ──────────────────────────────────────

    def _on_12306_validate(self):
        cookie = self._12306_cookie.get().strip()
        if not cookie:
            self._log_12306("请先粘贴 Cookie，再点校验", "fail")
            return
        self._12306_validate_btn.configure(state="disabled")
        self._log_12306("正在校验 Cookie ...", "info")

        def _work():
            try:
                sess = ticket12306.make_session(cookie)
                ok, msg = ticket12306.validate_cookie(sess)
            except Exception as e:
                ok, msg = False, f"{type(e).__name__}: {e}"
            self._ui(self._log_12306, msg, "ok" if ok else "fail")
            self._ui(self._12306_validate_btn.configure, state="normal")

        threading.Thread(target=_work, daemon=True).start()

    def _on_12306_start(self):
        if self._12306_worker.is_running():
            self._log_12306("已有查票任务在运行", "fail")
            return

        cookie = self._12306_cookie.get().strip()
        from_name = self._12306_from.get().strip()
        to_name = self._12306_to.get().strip()
        date = self._12306_date.get().strip()
        if not (cookie and from_name and to_name and date):
            self._log_12306("请先填写 Cookie / 出发站 / 到达站 / 出发日期", "fail")
            return
        types = [t for t, v in self._12306_types.items() if v.get()]
        seat = self._12306_seat.get()
        when_mode = self._12306_when_mode.get()
        when_str = self._12306_when.get().strip()
        auto_order = self._12306_auto_order.get()
        dry_run = self._12306_dry_run.get()

        passenger_names: list[str] = []
        if auto_order:
            sel = self._12306_pax_list.get_selected_indices()
            if not sel:
                self._log_12306(
                    "已开启自动下单但未选乘客，请先点「加载乘客」并勾选", "fail"
                )
                return
            if len(sel) > 2:
                self._log_12306("最多只能选 2 位乘客", "fail")
                return
            passenger_names = [self._12306_pax_data[i]["passenger_name"] for i in sel]
            mode_text = "Dry-run（不真实提交）" if dry_run else "REAL（真实下单）"
            confirm_msg = (
                f"你已开启「自动下单」({mode_text})\n\n"
                f"乘客：{', '.join(passenger_names)}\n"
                f"车次类型：{','.join(types) or '全部'}\n"
                f"席别：{seat}\n\n"
                f"风险确认：\n"
                f"• 自动下单违反 12306 TOS，可能触发账号风控/封停\n"
                f"• 命中后将自动走 7 步下单链\n"
                f"• 出票成功仍需你 30 分钟内手动支付\n"
                f"• 触发滑块/风控立即停止\n\n"
                f"是否继续？"
            )
            if not messagebox.askyesno("自动下单二次确认", confirm_msg):
                self._log_12306("用户取消启动", "info")
                return

        self._12306_worker.on_log = lambda m, tag="info": self._ui(
            self._log_12306, m, tag
        )
        self._12306_worker.on_status = lambda s: self._ui(self._12306_status.set, s)
        self._12306_worker.on_finish = lambda: self._ui(self._on_12306_finish)

        self._log_12306(
            f"开始查票：{from_name} → {to_name} {date} 席别={seat} "
            f"车次={','.join(types) or '全部'} 模式={when_mode} "
            f"自动下单={'是' if auto_order else '否'}"
            + (f"({'DRY' if dry_run else 'REAL'})" if auto_order else ""),
            "info",
        )
        try:
            interval = max(1, int(self._12306_interval.get()))
        except (TypeError, tk.TclError):
            interval = 3
        self._12306_status.set("运行中")
        self._12306_start_btn.configure(state="disabled")
        self._12306_stop_btn.configure(state="normal")
        self._12306_worker.start(
            cookie, from_name, to_name, date, types, seat,
            when_mode, when_str, interval,
            auto_order, dry_run, passenger_names,
        )

    def _on_12306_load_passengers(self):
        cookie = self._12306_cookie.get().strip()
        if not cookie:
            self._log_12306("请先粘贴 Cookie 再加载乘客", "fail")
            return
        self._12306_pax_status.set("加载中 ...")

        def _work():
            try:
                sess = ticket12306.make_session(cookie)
                pax = ticket12306_order.fetch_passenger_list(sess)
            except Exception as e:
                self._ui(
                    self._12306_pax_status.set,
                    f"加载失败: {type(e).__name__}",
                )
                self._ui(
                    self._log_12306,
                    f"[加载乘客失败] {type(e).__name__}: {e}",
                    "fail",
                )
                return
            self._ui(self._populate_passengers, pax)

        threading.Thread(target=_work, daemon=True).start()

    def _populate_passengers(self, pax: list[dict]):
        self._12306_pax_data = pax
        items = []
        for p in pax:
            name = p.get("passenger_name", "?")
            id_no = p.get("passenger_id_no", "")
            id_mask = (id_no[:4] + "****" + id_no[-4:]) if len(id_no) >= 8 else id_no
            ptype_map = {"1": "成人", "2": "儿童", "3": "学生", "4": "残军"}
            ptype = ptype_map.get(p.get("passenger_type", ""), "?")
            items.append(f"{name}  {id_mask}  {ptype}")
        self._12306_pax_list.set_items(items)

        saved = list(self._config.get("12306_auto_order_passengers", []) or [])
        restored = []
        restore_idx = []
        for i, p in enumerate(pax):
            if p.get("passenger_name") in saved:
                restore_idx.append(i)
                restored.append(p["passenger_name"])
        if restore_idx:
            self._12306_pax_list.select_indices(restore_idx)

        self._12306_pax_status.set(
            f"已加载 {len(pax)} 位乘客"
            + (f"（已勾选: {', '.join(restored)}）" if restored else "")
        )
        self._log_12306(f"已加载 {len(pax)} 位常用联系人", "ok")

    def _on_12306_pax_select(self):
        sel = self._12306_pax_list.get_selected_indices()
        names = [self._12306_pax_data[i]["passenger_name"] for i in sel]
        self._config["12306_auto_order_passengers"] = names
        self._on_save()

    def _on_12306_stop(self):
        if not self._12306_worker.is_running():
            self._log_12306("当前没有查票任务", "info")
            return
        self._12306_worker.stop()
        self._log_12306("已请求停止...", "info")
        self._12306_stop_btn.configure(state="disabled")

    def _on_12306_finish(self):
        self._12306_status.set("已停止")
        self._12306_start_btn.configure(state="normal")
        self._12306_stop_btn.configure(state="disabled")
        self._log_12306("查票任务已结束", "info")

    # ── 浏览器半自动购票 ────────────────────────────────

    def _ensure_browser(self) -> BrowserSession | None:
        if self._browser and self._browser.page is not None:
            return self._browser
        if not self._config.get("chrome_path"):
            detected = detect_chrome_path()
            if detected:
                self._config["chrome_path"] = detected
                self._on_save()
                self._ui(self._log_12306, f"自动探测到浏览器：{detected}", "info")
            else:
                self._ui(
                    self._log_12306,
                    "未找到 Chrome / Edge 浏览器，请在 config.json 的 chrome_path "
                    "中手动指定可执行文件路径。",
                    "fail",
                )
                return None
        try:
            self._browser = make_browser_session(self._config)
            self._browser.open(
                on_log=lambda m, t="info": self._ui(self._log_12306, m, t)
            )
            return self._browser
        except Exception as e:
            self._ui(
                self._log_12306,
                f"启动浏览器失败：{type(e).__name__}: {e}",
                "fail",
            )
            self._browser = None
            return None

    def _on_12306_browser_login(self):
        self._12306_login_btn.configure(state="disabled")
        self._log_12306("正在启动浏览器以登录 12306 ...", "info")

        def _work():
            try:
                browser = self._ensure_browser()
                if browser:
                    browser.open_12306_login(
                        on_log=lambda m, t="info": self._ui(self._log_12306, m, t)
                    )
            except Exception as e:
                self._ui(
                    self._log_12306,
                    f"[浏览器异常] {type(e).__name__}: {e}",
                    "fail",
                )
            finally:
                self._ui(self._12306_login_btn.configure, state="normal")

        threading.Thread(target=_work, daemon=True).start()

    def _on_12306_browser_buy(self):
        from_name = self._12306_from.get().strip()
        to_name = self._12306_to.get().strip()
        date = self._12306_date.get().strip()
        if not (from_name and to_name and date):
            self._log_12306("请先填写 出发站 / 到达站 / 出发日期", "fail")
            return

        self._12306_browser_btn.configure(state="disabled")
        self._log_12306(
            f"正在用浏览器打开购票页：{from_name} → {to_name} {date} ...", "info"
        )

        def _work():
            try:
                browser = self._ensure_browser()
                if browser:
                    browser.open_12306_query(
                        from_name, to_name, date,
                        on_log=lambda m, t="info": self._ui(self._log_12306, m, t),
                    )
                    self._ui(
                        self._log_12306,
                        "下一步请在浏览器中：① 点查询  ② 选车次  ③ 选乘客  "
                        "④ 过滑块  ⑤ 30 分钟内支付。",
                        "ok",
                    )
            except Exception as e:
                self._ui(
                    self._log_12306,
                    f"[浏览器异常] {type(e).__name__}: {e}",
                    "fail",
                )
            finally:
                self._ui(self._12306_browser_btn.configure, state="normal")

        threading.Thread(target=_work, daemon=True).start()

    def _on_damai_browser_open(self):
        url = self._damai_url.get().strip()

        def _work():
            try:
                if self._browser is None or self._browser.page is None:
                    self._browser = make_browser_session(self._config)
                    self._browser.open(
                        on_log=lambda m, t="info": self._ui(self._log_damai, m, t)
                    )
                self._browser.open_damai(
                    url, on_log=lambda m, t="info": self._ui(self._log_damai, m, t)
                )
            except Exception as e:
                self._ui(
                    self._log_damai,
                    f"[浏览器异常] {type(e).__name__}: {e}",
                    "fail",
                )

        threading.Thread(target=_work, daemon=True).start()

    # ── 大麦回调 ────────────────────────────────────────

    def _on_damai_validate(self):
        cookie = self._damai_cookie.get().strip()
        if not cookie:
            self._log_damai("请先粘贴 Cookie，再点校验", "fail")
            return
        self._damai_validate_btn.configure(state="disabled")
        self._log_damai("正在校验 Cookie ...", "info")

        def _work():
            try:
                sess = damai.make_session(cookie)
                ok, msg = damai.validate_cookie(sess)
            except Exception as e:
                ok, msg = False, f"{type(e).__name__}: {e}"
            self._ui(self._log_damai, msg, "ok" if ok else "fail")
            self._ui(self._damai_validate_btn.configure, state="normal")

        threading.Thread(target=_work, daemon=True).start()

    def _on_damai_start(self):
        if self._damai_worker.is_running():
            self._log_damai("已有查票任务在运行", "fail")
            return

        cookie = self._damai_cookie.get().strip()
        url_or_id = self._damai_url.get().strip()
        if not (cookie and url_or_id):
            self._log_damai("请先填写 Cookie 与 演出 URL/ID", "fail")
            return
        when_mode = self._damai_when_mode.get()
        when_str = self._damai_when.get().strip()
        try:
            interval = max(1, int(self._damai_interval.get()))
        except (TypeError, tk.TclError):
            interval = 2

        self._damai_worker.on_log = lambda m, tag="info": self._ui(
            self._log_damai, m, tag
        )
        self._damai_worker.on_status = lambda s: self._ui(self._damai_status.set, s)
        self._damai_worker.on_finish = lambda: self._ui(self._on_damai_finish)

        self._log_damai(
            f"开始查票：{url_or_id} 模式={when_mode} 间隔={interval}s",
            "info",
        )
        self._damai_status.set("运行中")
        self._damai_start_btn.configure(state="disabled")
        self._damai_stop_btn.configure(state="normal")
        self._damai_worker.start(cookie, url_or_id, when_mode, when_str, interval)

    def _on_damai_stop(self):
        if not self._damai_worker.is_running():
            self._log_damai("当前没有查票任务", "info")
            return
        self._damai_worker.stop()
        self._log_damai("已请求停止...", "info")
        self._damai_stop_btn.configure(state="disabled")

    def _on_damai_finish(self):
        self._damai_status.set("已停止")
        self._damai_start_btn.configure(state="normal")
        self._damai_stop_btn.configure(state="disabled")
        self._log_damai("查票任务已结束", "info")
