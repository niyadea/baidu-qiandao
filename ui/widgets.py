"""Win11 Fluent Design 自绘控件库。

集中所有自绘 CustomTkinter 控件：
  • Card             —— Fluent 浅色卡片（带 1px 边框、8px 圆角）
  • SectionCard      —— Card + 顶部标题
  • LogView          —— 日志面板（带 tag 着色 + 时间戳 + 日切清空 + 清空按钮）
  • IntSpinBox       —— Win11 NumberBox 风格的整数加减
  • SelectableList   —— 自动随主题切换配色的多选列表
  • ProgressWithLabel—— 进度条 + 右侧 N/M 计数
  • accent_button    —— Accent (主) 按钮工厂
  • standard_button  —— 标准（次要）按钮工厂
  • subtle_button    —— 透明按钮工厂（用于工具栏）
"""

from __future__ import annotations

import datetime as _dt
import tkinter as tk
from typing import Callable, Iterable

import customtkinter as ctk

from . import styling as S


# ── 按钮工厂 ────────────────────────────────────────────


def accent_button(parent, text: str, command: Callable, **kw) -> ctk.CTkButton:
    defaults = dict(
        text=text,
        command=command,
        height=S.BUTTON_HEIGHT,
        corner_radius=S.RADIUS_BUTTON,
        fg_color=S.accent_pair(),
        hover_color=S.accent_hover_pair(),
        text_color=S.TEXT_ON_ACCENT,
        font=S.font_body(),
        border_width=0,
    )
    defaults.update(kw)
    return ctk.CTkButton(parent, **defaults)


def standard_button(parent, text: str, command: Callable, **kw) -> ctk.CTkButton:
    defaults = dict(
        text=text,
        command=command,
        height=S.BUTTON_HEIGHT,
        corner_radius=S.RADIUS_BUTTON,
        fg_color=("#FBFBFB", "#373737"),
        hover_color=("#F5F5F5", "#404040"),
        text_color=S.TEXT_PRIMARY,
        border_color=("#D4D4D4", "#1A1A1A"),
        border_width=1,
        font=S.font_body(),
    )
    defaults.update(kw)
    return ctk.CTkButton(parent, **defaults)


def subtle_button(parent, text: str, command: Callable, **kw) -> ctk.CTkButton:
    defaults = dict(
        text=text,
        command=command,
        height=S.COMPACT_BUTTON_HEIGHT,
        corner_radius=S.RADIUS_BUTTON,
        fg_color="transparent",
        hover_color=S.HOVER_FILL,
        text_color=S.TEXT_PRIMARY,
        border_width=0,
        font=S.font_body(),
    )
    defaults.update(kw)
    return ctk.CTkButton(parent, **defaults)


def danger_button(parent, text: str, command: Callable, **kw) -> ctk.CTkButton:
    defaults = dict(
        text=text,
        command=command,
        height=S.BUTTON_HEIGHT,
        corner_radius=S.RADIUS_BUTTON,
        fg_color=("#C42B1C", "#5C1A1A"),
        hover_color=("#A8281A", "#742222"),
        text_color="#FFFFFF",
        font=S.font_body(),
        border_width=0,
    )
    defaults.update(kw)
    return ctk.CTkButton(parent, **defaults)


# ── Card / SectionCard ──────────────────────────────────


class Card(ctk.CTkFrame):
    """Fluent 浅色卡片：白底 + 1px 浅边框 + 8px 圆角。"""

    def __init__(self, master, **kwargs):
        defaults = dict(
            corner_radius=S.RADIUS_CARD,
            border_width=1,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER,
        )
        defaults.update(kwargs)
        super().__init__(master, **defaults)


class SectionCard(Card):
    """带标题的 Fluent 卡片；子控件挂在 ``card.body``。"""

    def __init__(
        self,
        master,
        title: str = "",
        *,
        body_padx: int = S.SPACE_LG,
        body_pady: tuple[int, int] = (S.SPACE_SM, S.SPACE_LG),
        **frame_kwargs,
    ):
        super().__init__(master, **frame_kwargs)
        if title:
            ctk.CTkLabel(
                self,
                text=title,
                anchor="w",
                font=S.font_strong(S.BODY_STRONG),
                text_color=S.TEXT_PRIMARY,
            ).pack(
                fill="x", padx=S.SPACE_LG, pady=(S.SPACE_MD, 0)
            )
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=body_padx, pady=body_pady)


# ── LogView ─────────────────────────────────────────────


class LogView(ctk.CTkFrame):
    """日志面板：时间戳 + tag 着色 + 日切清空 + 清空按钮。"""

    def __init__(
        self,
        master,
        *,
        height: int = 160,
        title: str = "",
        roll_on_new_day: bool = True,
        show_clear_btn: bool = True,
        **frame_kwargs,
    ):
        defaults = dict(fg_color="transparent")
        defaults.update(frame_kwargs)
        super().__init__(master, **defaults)
        self._roll = roll_on_new_day
        self._log_date: _dt.date | None = None

        if title or show_clear_btn:
            top = ctk.CTkFrame(self, fg_color="transparent", height=28)
            top.pack(fill="x", pady=(0, S.SPACE_XS))
            top.pack_propagate(False)
            if title:
                ctk.CTkLabel(
                    top, text=title, font=S.font_strong(), anchor="w",
                    text_color=S.TEXT_PRIMARY,
                ).pack(side="left")
            if show_clear_btn:
                subtle_button(
                    top, "清空", self.clear, width=56,
                    height=24,
                ).pack(side="right")

        self._text = ctk.CTkTextbox(
            self,
            height=height,
            font=S.font_mono(S.CAPTION),
            wrap="word",
            corner_radius=S.RADIUS_INPUT,
            border_width=1,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
        )
        self._text.pack(fill="both", expand=True)
        self._text.configure(state="disabled")
        self._text.tag_config("ok", foreground=_pick(S.OK))
        self._text.tag_config("fail", foreground=_pick(S.FAIL))
        self._text.tag_config("info", foreground=_pick(S.INFO))
        self._text.tag_config("muted", foreground=_pick(S.TEXT_TERTIARY))

    def log(self, text: str, tag: str = "info"):
        if self._roll:
            self._roll_if_new_day()
        ts = _dt.datetime.now().strftime("%H:%M:%S")
        self._text.configure(state="normal")
        self._text.insert("end", f"[{ts}] {text}\n", tag if tag else None)
        self._text.see("end")
        self._text.configure(state="disabled")

    def clear(self):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")
        self._log_date = None

    def refresh_theme(self):
        self._text.tag_config("ok", foreground=_pick(S.OK))
        self._text.tag_config("fail", foreground=_pick(S.FAIL))
        self._text.tag_config("info", foreground=_pick(S.INFO))
        self._text.tag_config("muted", foreground=_pick(S.TEXT_TERTIARY))

    def _roll_if_new_day(self):
        today = _dt.date.today()
        if self._log_date == today:
            return
        if self._log_date is not None:
            self._text.configure(state="normal")
            self._text.delete("1.0", "end")
            self._text.configure(state="disabled")
        self._text.configure(state="normal")
        self._text.insert(
            "end", f"━━━━━━ {today.isoformat()} ━━━━━━\n", "muted"
        )
        self._text.configure(state="disabled")
        self._log_date = today


def _pick(color_pair) -> str:
    """从 (light, dark) 二元组中根据当前主题挑一个具体颜色。"""
    if isinstance(color_pair, tuple):
        return color_pair[1] if S.is_dark() else color_pair[0]
    return color_pair


# ── IntSpinBox（Win11 NumberBox 风格） ─────────────────


class IntSpinBox(ctk.CTkFrame):
    """Win11 NumberBox 风格的整数加减；左右按钮无边框、悬停灰底。"""

    def __init__(
        self,
        master,
        *,
        from_: int = 0,
        to: int = 100,
        textvariable: tk.IntVar | tk.StringVar | None = None,
        width: int = 110,
        step: int = 1,
        on_change: Callable[[int], None] | None = None,
        **frame_kwargs,
    ):
        defaults = dict(
            corner_radius=S.RADIUS_INPUT,
            border_width=1,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
        )
        defaults.update(frame_kwargs)
        super().__init__(master, **defaults)
        self._min = int(from_)
        self._max = int(to)
        self._step = max(1, int(step))
        self._on_change = on_change
        self._var: tk.IntVar | tk.StringVar = textvariable or tk.IntVar(value=self._min)

        h = S.INPUT_HEIGHT - 2  # 减去 border
        btn_w = 28

        self._entry = ctk.CTkEntry(
            self,
            textvariable=self._var,
            width=max(40, width - 2 * btn_w - 4),
            height=h,
            justify="center",
            fg_color="transparent",
            border_width=0,
            font=S.font_body(),
            text_color=S.TEXT_PRIMARY,
        )
        self._entry.pack(side="left", padx=(2, 0), pady=1)

        ctk.CTkButton(
            self, text="−", width=btn_w, height=h,
            corner_radius=S.RADIUS_INPUT - 1,
            fg_color="transparent",
            hover_color=S.HOVER_FILL,
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(14),
            border_width=0,
            command=self._dec,
        ).pack(side="left", pady=1)
        ctk.CTkButton(
            self, text="+", width=btn_w, height=h,
            corner_radius=S.RADIUS_INPUT - 1,
            fg_color="transparent",
            hover_color=S.HOVER_FILL,
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(14),
            border_width=0,
            command=self._inc,
        ).pack(side="left", padx=(0, 2), pady=1)

        self._var.trace_add("write", self._on_var_change)

    def _read(self) -> int:
        try:
            return int(str(self._var.get()).strip() or self._min)
        except (TypeError, tk.TclError, ValueError):
            return self._min

    def _write(self, value: int):
        clamped = max(self._min, min(self._max, value))
        if isinstance(self._var, tk.IntVar):
            if self._var.get() != clamped:
                self._var.set(clamped)
        else:
            self._var.set(str(clamped))

    def _dec(self):
        self._write(self._read() - self._step)

    def _inc(self):
        self._write(self._read() + self._step)

    def _on_var_change(self, *_):
        if self._on_change:
            try:
                self._on_change(self._read())
            except Exception:
                pass


# ── SelectableList ──────────────────────────────────────


class SelectableList(ctk.CTkFrame):
    """跟随主题的多选列表，封装 tk.Listbox。"""

    def __init__(
        self,
        master,
        *,
        height: int = 5,
        selectmode: str = "extended",
        **frame_kwargs,
    ):
        defaults = dict(
            corner_radius=S.RADIUS_INPUT,
            border_width=1,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
        )
        defaults.update(frame_kwargs)
        super().__init__(master, **defaults)
        bg, fg, sel_bg, sel_fg = S.listbox_colors()
        self._listbox = tk.Listbox(
            self,
            height=height,
            selectmode=selectmode,
            exportselection=False,
            relief="flat",
            highlightthickness=0,
            borderwidth=0,
            bg=bg,
            fg=fg,
            selectbackground=sel_bg,
            selectforeground=sel_fg,
            activestyle="none",
            font=(_resolve_listbox_font(), 11),
        )
        self._listbox.pack(fill="both", expand=True, padx=4, pady=4)

    def set_items(self, items: Iterable[str]):
        self._listbox.delete(0, "end")
        for it in items:
            self._listbox.insert("end", it)

    def get_selected_indices(self) -> list[int]:
        return list(self._listbox.curselection())

    def select_indices(self, indices: Iterable[int]):
        for i in indices:
            self._listbox.selection_set(i)

    def bind_select(self, callback: Callable[[], None]):
        self._listbox.bind("<<ListboxSelect>>", lambda _e: callback())

    def refresh_theme(self):
        bg, fg, sel_bg, sel_fg = S.listbox_colors()
        self._listbox.configure(
            bg=bg, fg=fg, selectbackground=sel_bg, selectforeground=sel_fg
        )


def _resolve_listbox_font() -> str:
    from tkinter import font as tkfont
    fams = tkfont.families()
    for f in (S.UI_FONT_FAMILY, S.UI_FONT_FAMILY_FALLBACK, "Segoe UI"):
        if f in fams:
            return f
    return "TkDefaultFont"


# ── ProgressWithLabel ───────────────────────────────────


class ProgressWithLabel(ctk.CTkFrame):
    """进度条 + 右侧 N/M 计数文字。兼容 ttk.Progressbar 调用方式。"""

    def __init__(self, master, *, height: int = 6, **frame_kwargs):
        defaults = dict(fg_color="transparent")
        defaults.update(frame_kwargs)
        super().__init__(master, **defaults)
        self._max = 1
        self._value = 0

        self._bar = ctk.CTkProgressBar(
            self, height=height,
            corner_radius=height // 2,
            progress_color=S.accent_pair(),
            fg_color=S.LAYER_BORDER,
        )
        self._bar.set(0)
        self._bar.pack(side="left", fill="x", expand=True, padx=(0, S.SPACE_SM))
        self._label_var = tk.StringVar(value="")
        ctk.CTkLabel(
            self,
            textvariable=self._label_var,
            font=S.font_mono(S.CAPTION),
            text_color=S.TEXT_TERTIARY,
            width=70,
            anchor="e",
        ).pack(side="right")

    def configure(self, **kw):
        if "maximum" in kw:
            self._max = max(1, int(kw["maximum"]))
            self._value = 0
            self._sync()
        if "value" in kw:
            self.set_value(int(kw["value"]))

    def __setitem__(self, key, value):
        if key == "value":
            self.set_value(int(value))
        elif key == "maximum":
            self._max = max(1, int(value))
            self._sync()

    def set_value(self, value: int):
        self._value = max(0, min(self._max, int(value)))
        self._sync()

    def reset(self):
        self._value = 0
        self._max = 1
        self._sync()
        self._label_var.set("")

    def _sync(self):
        self._bar.set(self._value / self._max if self._max else 0)
        if self._max > 1:
            self._label_var.set(f"{self._value} / {self._max}")
        else:
            pct = int((self._value / self._max) * 100) if self._max else 0
            self._label_var.set(f"{pct}%" if self._value else "")


# ── PivotTabs ───────────────────────────────────────────


class PivotTabs(ctk.CTkFrame):
    """Win11 / 百度贴吧 风格 tab：选中文字 accent 色 + 底部 2px 下划线指示器。

    与 ``ctk.CTkTabview`` 的常用 API 兼容：
        tab = pivot.add("名字")     # 返回内容 frame，直接往上面放控件
        pivot.set("名字")           # 切换激活 tab
        pivot.get() -> str          # 当前激活 tab 名字
    """

    def __init__(self, master, **kw):
        defaults = dict(fg_color="transparent")
        defaults.update(kw)
        super().__init__(master, **defaults)

        self._bar = ctk.CTkFrame(self, fg_color="transparent")
        self._bar.pack(fill="x")

        ctk.CTkFrame(self, fg_color=S.LAYER_BORDER, height=1).pack(
            fill="x", pady=(0, S.SPACE_SM)
        )

        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True)

        self._tabs: dict[str, ctk.CTkFrame] = {}
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._indicators: dict[str, ctk.CTkFrame] = {}
        self._current: str | None = None

    def add(self, name: str) -> ctk.CTkFrame:
        col = ctk.CTkFrame(self._bar, fg_color="transparent")
        col.pack(side="left", padx=(0, S.SPACE_SM))

        btn = ctk.CTkButton(
            col, text=name,
            height=30,
            fg_color="transparent",
            hover_color=S.HOVER_FILL,
            text_color=S.TEXT_PRIMARY,
            border_width=0,
            corner_radius=S.RADIUS_BUTTON,
            font=S.font_strong(S.BODY),
            command=lambda n=name: self.set(n),
        )
        btn.pack(side="top", padx=2, pady=(2, 0))

        indicator = ctk.CTkFrame(
            col, fg_color="transparent", height=2, corner_radius=1,
        )
        indicator.pack(side="top", fill="x", padx=S.SPACE_MD, pady=(3, 0))
        indicator.pack_propagate(False)

        content = ctk.CTkFrame(self._content, fg_color="transparent")

        self._buttons[name] = btn
        self._indicators[name] = indicator
        self._tabs[name] = content

        if self._current is None:
            self.set(name)
        return content

    def set(self, name: str):
        if name not in self._tabs or self._current == name:
            return
        if self._current is not None:
            self._tabs[self._current].pack_forget()
            self._indicators[self._current].configure(fg_color="transparent")
            self._buttons[self._current].configure(
                text_color=S.TEXT_PRIMARY, font=S.font_body(S.BODY),
            )
        self._tabs[name].pack(fill="both", expand=True)
        self._indicators[name].configure(fg_color=S.accent_pair())
        self._buttons[name].configure(
            text_color=S.accent_pair(), font=S.font_strong(S.BODY),
        )
        self._current = name

    def get(self) -> str | None:
        return self._current

    def refresh_theme(self):
        """主题切换后调用，重新染色 active indicator/text。"""
        for n, ind in self._indicators.items():
            ind.configure(
                fg_color=S.accent_pair() if n == self._current else "transparent"
            )
        for n, btn in self._buttons.items():
            btn.configure(
                text_color=S.accent_pair() if n == self._current else S.TEXT_PRIMARY
            )


# ── 工具：取浅/深主题对应色 ─────────────────────────


def color(pair) -> str | tuple[str, str]:
    """直接返回 (light, dark) 二元组，CTk 控件接受这种格式自动按主题选择。"""
    return pair
