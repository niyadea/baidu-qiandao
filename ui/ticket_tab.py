"""抢票功能页签 UI（含 Cookie 获取帮助与下单前查询逻辑入口）。"""

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from core import damai, ticket12306, ticket12306_order

from .ticket_worker import DamaiWorker, Ticket12306Worker

FEASIBILITY_TEXT = (
    "⚠ 可行性说明：\n"
    "  • 12306：官方有验证码、滑块、风控与排队机制，开源方案（如 py12306）\n"
    "    可在抢候补、捡漏场景部分可用；遇到春运/热门车次，单机命中率有限。\n"
    "  • 大麦网：人机校验极强（IP+设备指纹+行为校验），靠 HTTP 协议刷接口\n"
    "    几乎不可行；可行思路是浏览器自动化（Selenium/Playwright）+ 人工\n"
    "    完成验证码，仍存在账号风控风险。\n"
    "  • 本工具仅做「下单之前」的查询/轮询/提醒；不会自动下单，切勿用于黄牛/牟利。"
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


class TicketTab(ttk.Frame):
    """抢票主页签：内含 12306 / 大麦网 / 说明 三个子页签。"""

    def __init__(
        self,
        parent,
        config_data: dict | None = None,
        on_save: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self._config = config_data if config_data is not None else {}
        self._on_save = on_save or (lambda: None)
        self._12306_worker = Ticket12306Worker()
        self._damai_worker = DamaiWorker()
        self._build()
        self._bind_persistence()

    def _build(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        tab12306 = ttk.Frame(nb)
        nb.add(tab12306, text="12306 火车票")
        self._build_12306(tab12306)

        tab_damai = ttk.Frame(nb)
        nb.add(tab_damai, text="大麦网")
        self._build_damai(tab_damai)

        tab_info = ttk.Frame(nb)
        nb.add(tab_info, text="说明")
        self._build_info(tab_info)

    def _bind_persistence(self):
        """启动加载完成后绑定 12306 自动下单 4 字段的双向持久化。"""

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
        self._12306_pax_list.bind("<<ListboxSelect>>", self._on_12306_pax_select)

    # ── 12306 子页 ──────────────────────────────────────

    def _build_12306(self, parent):
        pad = {"padx": 8, "pady": 4}

        frm_acct = ttk.LabelFrame(parent, text="12306 登录 Cookie", padding=6)
        frm_acct.pack(fill="x", **pad)
        ttk.Label(frm_acct, text="Cookie:").grid(row=0, column=0, sticky="e")
        self._12306_cookie = tk.StringVar()
        ttk.Entry(frm_acct, textvariable=self._12306_cookie, width=58, show="*").grid(
            row=0, column=1, padx=4, sticky="ew"
        )
        self._12306_validate_btn = ttk.Button(
            frm_acct, text="校验 Cookie", command=self._on_12306_validate
        )
        self._12306_validate_btn.grid(row=0, column=2, padx=(4, 0))
        ttk.Button(
            frm_acct,
            text="?",
            width=2,
            command=lambda: self._show_cookie_help("12306"),
        ).grid(row=0, column=3, padx=(4, 0))
        frm_acct.columnconfigure(1, weight=1)

        frm_trip = ttk.LabelFrame(parent, text="行程", padding=6)
        frm_trip.pack(fill="x", **pad)
        ttk.Label(frm_trip, text="出发站:").grid(row=0, column=0, sticky="e")
        self._12306_from = tk.StringVar()
        ttk.Entry(frm_trip, textvariable=self._12306_from, width=14).grid(
            row=0, column=1, padx=4, sticky="w"
        )
        ttk.Label(frm_trip, text="到达站:").grid(
            row=0, column=2, sticky="e", padx=(12, 0)
        )
        self._12306_to = tk.StringVar()
        ttk.Entry(frm_trip, textvariable=self._12306_to, width=14).grid(
            row=0, column=3, padx=4, sticky="w"
        )
        ttk.Label(frm_trip, text="出发日期:").grid(
            row=1, column=0, sticky="e", pady=(4, 0)
        )
        self._12306_date = tk.StringVar()
        ttk.Entry(frm_trip, textvariable=self._12306_date, width=14).grid(
            row=1, column=1, padx=4, sticky="w", pady=(4, 0)
        )
        ttk.Label(frm_trip, text="(YYYY-MM-DD)").grid(
            row=1, column=2, columnspan=2, sticky="w", pady=(4, 0)
        )

        frm_train = ttk.LabelFrame(parent, text="车次 / 席别", padding=6)
        frm_train.pack(fill="x", **pad)
        ttk.Label(frm_train, text="车次类型:").grid(row=0, column=0, sticky="w")
        self._12306_types: dict[str, tk.BooleanVar] = {}
        for i, t in enumerate(["G/C", "D", "Z", "T", "K", "其他"]):
            var = tk.BooleanVar(value=t in ("G/C", "D"))
            self._12306_types[t] = var
            ttk.Checkbutton(frm_train, text=t, variable=var).grid(
                row=0, column=1 + i, padx=2, sticky="w"
            )
        ttk.Label(frm_train, text="席别:").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        self._12306_seat = tk.StringVar(value="二等座")
        ttk.Combobox(
            frm_train,
            textvariable=self._12306_seat,
            values=[
                "商务座",
                "特等座",
                "一等座",
                "二等座",
                "高级软卧",
                "软卧",
                "动卧",
                "硬卧",
                "软座",
                "硬座",
                "无座",
            ],
            state="readonly",
            width=12,
        ).grid(row=1, column=1, columnspan=3, sticky="w", padx=4, pady=(4, 0))

        frm_order = ttk.LabelFrame(
            parent,
            text="自动下单（高风险，违反 12306 TOS，封号风险自负）",
            padding=6,
        )
        frm_order.pack(fill="x", **pad)
        self._12306_auto_order = tk.BooleanVar(
            value=bool(self._config.get("12306_auto_order_enabled", False))
        )
        ttk.Checkbutton(
            frm_order,
            text="启用自动下单",
            variable=self._12306_auto_order,
        ).grid(row=0, column=0, sticky="w")
        self._12306_dry_run = tk.BooleanVar(
            value=bool(self._config.get("12306_auto_order_dry_run", True))
        )
        ttk.Checkbutton(
            frm_order,
            text="Dry-run 测试模式（推荐首次开启）",
            variable=self._12306_dry_run,
        ).grid(row=0, column=1, padx=(16, 0), sticky="w")
        ttk.Button(
            frm_order,
            text="加载乘客",
            command=self._on_12306_load_passengers,
        ).grid(row=1, column=0, pady=(6, 0), sticky="w")
        self._12306_pax_status = tk.StringVar(value="未加载（先填 Cookie 再点加载）")
        ttk.Label(frm_order, textvariable=self._12306_pax_status).grid(
            row=1, column=1, padx=(16, 0), pady=(6, 0), sticky="w"
        )
        ttk.Label(
            frm_order,
            text="选乘客（按住 Ctrl 多选，最多 2 人）:",
        ).grid(row=2, column=0, columnspan=2, pady=(6, 0), sticky="w")
        self._12306_pax_list = tk.Listbox(
            frm_order,
            height=4,
            selectmode="extended",
            exportselection=False,
        )
        self._12306_pax_list.grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(2, 0)
        )
        self._12306_pax_data: list[dict] = []
        frm_order.columnconfigure(1, weight=1)

        frm_when = ttk.LabelFrame(parent, text="抢票时间", padding=6)
        frm_when.pack(fill="x", **pad)
        self._12306_when_mode = tk.StringVar(value="now")
        ttk.Radiobutton(
            frm_when, text="立即开抢", variable=self._12306_when_mode, value="now"
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            frm_when, text="定时开抢:", variable=self._12306_when_mode, value="timed"
        ).grid(row=0, column=1, padx=(16, 4), sticky="w")
        self._12306_when = tk.StringVar(value="13:00:00")
        ttk.Entry(frm_when, textvariable=self._12306_when, width=10).grid(
            row=0, column=2, sticky="w"
        )
        ttk.Label(frm_when, text="(HH:MM:SS)").grid(
            row=0, column=3, padx=(4, 0), sticky="w"
        )
        ttk.Label(frm_when, text="查询间隔:").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        self._12306_interval = tk.IntVar(
            value=max(1, int(self._config.get("12306_query_interval", 3)))
        )
        ttk.Spinbox(
            frm_when,
            from_=1,
            to=60,
            textvariable=self._12306_interval,
            width=6,
        ).grid(row=1, column=1, padx=4, sticky="w", pady=(4, 0))
        ttk.Label(frm_when, text="秒/次（最低 1s）").grid(
            row=1, column=2, columnspan=2, sticky="w", pady=(4, 0)
        )

        frm_btn = ttk.Frame(parent)
        frm_btn.pack(fill="x", **pad)
        self._12306_start_btn = ttk.Button(
            frm_btn, text="开始查票", command=self._on_12306_start
        )
        self._12306_start_btn.pack(side="left")
        self._12306_stop_btn = ttk.Button(
            frm_btn, text="停止", command=self._on_12306_stop, state="disabled"
        )
        self._12306_stop_btn.pack(side="left", padx=(8, 0))
        self._12306_status = tk.StringVar(value="未开始")
        ttk.Label(frm_btn, textvariable=self._12306_status).pack(side="right")

        frm_log = ttk.LabelFrame(parent, text="状态日志", padding=4)
        frm_log.pack(fill="both", expand=True, **pad)
        self._12306_log = tk.Text(
            frm_log,
            height=8,
            state="disabled",
            font=("Consolas", 9),
            wrap="word",
        )
        sb = ttk.Scrollbar(frm_log, command=self._12306_log.yview)
        self._12306_log.configure(yscrollcommand=sb.set)
        self._12306_log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._12306_log.tag_configure("ok", foreground="#228B22")
        self._12306_log.tag_configure("fail", foreground="#CC0000")
        self._12306_log.tag_configure("info", foreground="#1E90FF")

    # ── 大麦网子页 ───────────────────────────────────────

    def _build_damai(self, parent):
        pad = {"padx": 8, "pady": 4}

        frm_acct = ttk.LabelFrame(parent, text="大麦登录 Cookie", padding=6)
        frm_acct.pack(fill="x", **pad)
        ttk.Label(frm_acct, text="Cookie:").grid(row=0, column=0, sticky="e")
        self._damai_cookie = tk.StringVar()
        ttk.Entry(frm_acct, textvariable=self._damai_cookie, width=58, show="*").grid(
            row=0, column=1, padx=4, sticky="ew"
        )
        self._damai_validate_btn = ttk.Button(
            frm_acct, text="校验 Cookie", command=self._on_damai_validate
        )
        self._damai_validate_btn.grid(row=0, column=2, padx=(4, 0))
        ttk.Button(
            frm_acct,
            text="?",
            width=2,
            command=lambda: self._show_cookie_help("damai"),
        ).grid(row=0, column=3, padx=(4, 0))
        frm_acct.columnconfigure(1, weight=1)

        frm_show = ttk.LabelFrame(parent, text="演出信息", padding=6)
        frm_show.pack(fill="x", **pad)
        ttk.Label(frm_show, text="演出 URL / ID:").grid(row=0, column=0, sticky="e")
        self._damai_url = tk.StringVar()
        ttk.Entry(frm_show, textvariable=self._damai_url, width=50).grid(
            row=0, column=1, columnspan=3, padx=4, sticky="ew", pady=2
        )
        ttk.Label(frm_show, text="场次:").grid(row=1, column=0, sticky="e")
        self._damai_session = tk.StringVar()
        ttk.Entry(frm_show, textvariable=self._damai_session, width=20).grid(
            row=1, column=1, padx=4, sticky="w"
        )
        ttk.Label(frm_show, text="票档:").grid(
            row=1, column=2, sticky="e", padx=(12, 0)
        )
        self._damai_price = tk.StringVar()
        ttk.Entry(frm_show, textvariable=self._damai_price, width=14).grid(
            row=1, column=3, padx=4, sticky="w"
        )
        ttk.Label(frm_show, text="数量:").grid(row=2, column=0, sticky="e", pady=(2, 0))
        self._damai_qty = tk.IntVar(value=1)
        ttk.Spinbox(
            frm_show, from_=1, to=4, textvariable=self._damai_qty, width=6
        ).grid(row=2, column=1, padx=4, sticky="w", pady=(2, 0))
        ttk.Label(frm_show, text="观演人:").grid(
            row=2, column=2, sticky="e", padx=(12, 0)
        )
        self._damai_viewer = tk.StringVar()
        ttk.Entry(frm_show, textvariable=self._damai_viewer, width=18).grid(
            row=2, column=3, padx=4, sticky="w", pady=(2, 0)
        )
        frm_show.columnconfigure(1, weight=1)

        frm_when = ttk.LabelFrame(parent, text="查票策略", padding=6)
        frm_when.pack(fill="x", **pad)
        self._damai_when_mode = tk.StringVar(value="now")
        ttk.Radiobutton(
            frm_when, text="立即查询", variable=self._damai_when_mode, value="now"
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            frm_when, text="定时开始:", variable=self._damai_when_mode, value="timed"
        ).grid(row=0, column=1, padx=(16, 4), sticky="w")
        self._damai_when = tk.StringVar(value="20:00:00")
        ttk.Entry(frm_when, textvariable=self._damai_when, width=10).grid(
            row=0, column=2, sticky="w"
        )
        ttk.Label(frm_when, text="(HH:MM:SS)").grid(
            row=0, column=3, padx=(4, 0), sticky="w"
        )
        ttk.Label(frm_when, text="轮询间隔:").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        self._damai_interval = tk.IntVar(value=2)
        ttk.Spinbox(
            frm_when, from_=1, to=30, textvariable=self._damai_interval, width=6
        ).grid(row=1, column=1, padx=4, sticky="w", pady=(4, 0))
        ttk.Label(frm_when, text="秒/次（库存出现时弹窗提醒，不会自动下单）").grid(
            row=1, column=2, columnspan=2, sticky="w", pady=(4, 0)
        )

        frm_btn = ttk.Frame(parent)
        frm_btn.pack(fill="x", **pad)
        self._damai_start_btn = ttk.Button(
            frm_btn, text="开始查票", command=self._on_damai_start
        )
        self._damai_start_btn.pack(side="left")
        self._damai_stop_btn = ttk.Button(
            frm_btn, text="停止", command=self._on_damai_stop, state="disabled"
        )
        self._damai_stop_btn.pack(side="left", padx=(8, 0))
        self._damai_status = tk.StringVar(value="未开始")
        ttk.Label(frm_btn, textvariable=self._damai_status).pack(side="right")

        frm_log = ttk.LabelFrame(parent, text="状态日志", padding=4)
        frm_log.pack(fill="both", expand=True, **pad)
        self._damai_log = tk.Text(
            frm_log,
            height=8,
            state="disabled",
            font=("Consolas", 9),
            wrap="word",
        )
        sb = ttk.Scrollbar(frm_log, command=self._damai_log.yview)
        self._damai_log.configure(yscrollcommand=sb.set)
        self._damai_log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._damai_log.tag_configure("ok", foreground="#228B22")
        self._damai_log.tag_configure("fail", foreground="#CC0000")
        self._damai_log.tag_configure("info", foreground="#1E90FF")

    # ── 说明子页 ─────────────────────────────────────────

    def _build_info(self, parent):
        text = tk.Text(parent, wrap="word", height=20, font=("Microsoft YaHei", 10))
        text.pack(fill="both", expand=True, padx=8, pady=8)
        text.insert("1.0", FEASIBILITY_TEXT)
        text.configure(state="disabled")

    # ── Cookie 帮助对话框 ───────────────────────────────

    def _show_cookie_help(self, site: str):
        title = "12306 Cookie 获取步骤" if site == "12306" else "大麦 Cookie 获取步骤"
        content = COOKIE_HELP_12306 if site == "12306" else COOKIE_HELP_DAMAI

        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("680x560")
        win.transient(self.winfo_toplevel())

        btn_bar = ttk.Frame(win)
        btn_bar.pack(side="bottom", fill="x", padx=8, pady=6)

        def _copy_all():
            self.clipboard_clear()
            self.clipboard_append(content)

        ttk.Button(btn_bar, text="关闭", command=win.destroy).pack(side="right")
        ttk.Button(btn_bar, text="复制全文", command=_copy_all).pack(
            side="right", padx=(0, 6)
        )

        text_frame = ttk.Frame(win)
        text_frame.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        text = tk.Text(
            text_frame, wrap="word", font=("Microsoft YaHei", 10), padx=8, pady=8
        )
        sb = ttk.Scrollbar(text_frame, command=text.yview)
        text.configure(yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        text.insert("1.0", content)
        text.configure(state="disabled")

    # ── 日志辅助 ────────────────────────────────────────

    def _log_to(self, widget: tk.Text, text: str, tag: str = "info"):
        import datetime as _dt

        ts = _dt.datetime.now().strftime("%H:%M:%S")
        widget.configure(state="normal")
        widget.insert("end", f"[{ts}] {text}\n", tag)
        widget.see("end")
        widget.configure(state="disabled")

    def _log_12306(self, text: str, tag: str = "info"):
        self._log_to(self._12306_log, text, tag)

    def _log_damai(self, text: str, tag: str = "info"):
        self._log_to(self._damai_log, text, tag)

    # ── 线程安全的 UI 调度 ──────────────────────────────

    def _ui(self, fn, *args, **kwargs):
        """从后台线程调度回主线程执行 UI 操作。"""
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
            sel = self._12306_pax_list.curselection()
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
            cookie,
            from_name,
            to_name,
            date,
            types,
            seat,
            when_mode,
            when_str,
            interval,
            auto_order,
            dry_run,
            passenger_names,
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
        self._12306_pax_list.delete(0, "end")
        for p in pax:
            name = p.get("passenger_name", "?")
            id_no = p.get("passenger_id_no", "")
            id_mask = (id_no[:4] + "****" + id_no[-4:]) if len(id_no) >= 8 else id_no
            ptype_map = {"1": "成人", "2": "儿童", "3": "学生", "4": "残军"}
            ptype = ptype_map.get(p.get("passenger_type", ""), "?")
            self._12306_pax_list.insert("end", f"{name}  {id_mask}  {ptype}")
        saved = list(self._config.get("12306_auto_order_passengers", []) or [])
        restored = []
        for i, p in enumerate(pax):
            if p.get("passenger_name") in saved:
                self._12306_pax_list.selection_set(i)
                restored.append(p["passenger_name"])
        self._12306_pax_status.set(
            f"已加载 {len(pax)} 位乘客"
            + (f"（已勾选: {', '.join(restored)}）" if restored else "")
        )
        self._log_12306(f"已加载 {len(pax)} 位常用联系人", "ok")

    def _on_12306_pax_select(self, _event=None):
        sel = self._12306_pax_list.curselection()
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
