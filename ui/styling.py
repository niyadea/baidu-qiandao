"""Win11 Fluent Design 视觉常量。

颜色 / 字号 / 圆角 / 间距全部按 Microsoft Fluent Design v2 规范取值，
确保整套 UI 与系统原生应用观感一致。
"""

import customtkinter as ctk

# ── Accent (Win11 系统默认蓝 - 比 Settings 标题色再浅一档) ──

ACCENT = "#3B82F6"
ACCENT_HOVER = "#2563EB"
ACCENT_PRESS = "#1D4ED8"
ACCENT_DARK = "#60A5FA"
ACCENT_DARK_HOVER = "#93C5FD"

# 浅蓝（用于窗口标题栏/边框装饰）
ACCENT_TITLE = "#DDEBFD"
ACCENT_TITLE_DARK = "#1E3A8A"
ACCENT_BORDER = "#A8C8F4"
ACCENT_BORDER_DARK = "#3D5B8C"

# ── Fill / Background (浅色 / 深色) ────────────────────

WIN_BG = ("#F3F3F3", "#202020")
LAYER = ("#FFFFFF", "#2B2B2B")
LAYER_ALT = ("#F9F9F9", "#262626")
LAYER_SUBTLE = ("#FAFAFA", "#2D2D2D")
LAYER_BORDER = ("#ECECEC", "#1F1F1F")
HOVER_FILL = ("#F5F5F5", "#2F2F2F")

# ── Text ────────────────────────────────────────────────

TEXT_PRIMARY = ("#1A1A1A", "#FFFFFF")
TEXT_SECONDARY = ("#5C5C5C", "#C7C7C7")
TEXT_TERTIARY = ("#8B8B8B", "#9D9D9D")
TEXT_DISABLED = ("#A3A3A3", "#666666")
TEXT_ON_ACCENT = "#FFFFFF"

# ── 状态色 ──────────────────────────────────────────────

OK = ("#0F7B0F", "#6CCB5F")
FAIL = ("#C42B1C", "#FF99A4")
INFO = ("#3B82F6", "#60A5FA")
WARNING = ("#9D5D00", "#FCE100")

# ── Listbox（CTk 没原生组件，用 tk.Listbox 兜底） ────

LISTBOX_BG_LIGHT = "#FAFAFA"
LISTBOX_BG_DARK = "#2D2D2D"
LISTBOX_FG_LIGHT = "#1A1A1A"
LISTBOX_FG_DARK = "#FFFFFF"
LISTBOX_SEL_BG = "#3B82F6"
LISTBOX_SEL_FG = "#FFFFFF"

# ── 圆角（Win11 标准） ─────────────────────────────────

RADIUS_CARD = 8
RADIUS_BUTTON = 4
RADIUS_INPUT = 4
RADIUS_LIST_ITEM = 4

# ── 间距 ────────────────────────────────────────────────

SPACE_XXS = 2
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 20
SPACE_XXL = 24

# ── 控件尺寸 ────────────────────────────────────────────

INPUT_HEIGHT = 32
BUTTON_HEIGHT = 32
COMPACT_BUTTON_HEIGHT = 28
ICON_BUTTON_SIZE = 32

# ── 字体（Win11 默认是 Segoe UI Variable） ─────────────

UI_FONT_FAMILY = "Segoe UI Variable Text"
UI_FONT_FAMILY_FALLBACK = "Microsoft YaHei UI"
TITLE_FONT_FAMILY = "Segoe UI Variable Display"
MONO_FONT_FAMILY = "Cascadia Mono"
MONO_FONT_FALLBACK = "Consolas"

CAPTION = 11
BODY = 13
BODY_STRONG = 13
SUBTITLE = 16
TITLE = 20
TITLE_LARGE = 28


def _has_font(name: str) -> bool:
    """检测字体是否存在；不存在时回退到中文兜底。"""
    try:
        from tkinter import font as tkfont
        return name in tkfont.families()
    except Exception:
        return False


_FONT_CHECKED = {"ui": None, "title": None, "mono": None}


def _resolve_font(kind: str, primary: str, fallback: str) -> str:
    cached = _FONT_CHECKED.get(kind)
    if cached is not None:
        return cached
    chosen = primary if _has_font(primary) else fallback
    _FONT_CHECKED[kind] = chosen
    return chosen


def font_body(size: int = BODY, weight: str = "normal") -> ctk.CTkFont:
    family = _resolve_font("ui", UI_FONT_FAMILY, UI_FONT_FAMILY_FALLBACK)
    return ctk.CTkFont(family=family, size=size, weight=weight)


def font_strong(size: int = BODY_STRONG) -> ctk.CTkFont:
    return font_body(size=size, weight="bold")


def font_title(size: int = SUBTITLE) -> ctk.CTkFont:
    family = _resolve_font("title", TITLE_FONT_FAMILY, UI_FONT_FAMILY_FALLBACK)
    return ctk.CTkFont(family=family, size=size, weight="bold")


def font_mono(size: int = CAPTION) -> ctk.CTkFont:
    family = _resolve_font("mono", MONO_FONT_FAMILY, MONO_FONT_FALLBACK)
    return ctk.CTkFont(family=family, size=size)


# ── 颜色辅助 ────────────────────────────────────────────


def is_dark() -> bool:
    return ctk.get_appearance_mode() == "Dark"


def listbox_colors() -> tuple[str, str, str, str]:
    """返回 (bg, fg, sel_bg, sel_fg)，跟随当前主题。"""
    if is_dark():
        return LISTBOX_BG_DARK, LISTBOX_FG_DARK, LISTBOX_SEL_BG, LISTBOX_SEL_FG
    return LISTBOX_BG_LIGHT, LISTBOX_FG_LIGHT, LISTBOX_SEL_BG, LISTBOX_SEL_FG


def accent_pair() -> tuple[str, str]:
    """返回 (light_accent, dark_accent) 二元组，供 fg_color 使用。"""
    return (ACCENT, ACCENT_DARK)


def accent_hover_pair() -> tuple[str, str]:
    return (ACCENT_HOVER, ACCENT_DARK_HOVER)


# ── 窗口外观（标题栏 / 边框 / Mica） ──────────────────


def apply_window_chrome(window, dark: bool | None = None) -> bool:
    """给窗口装饰应用 Win11 风格：

    • 浅色主题：标题栏 + 边框使用淡蓝色（来自 ACCENT 色族）；
    • 深色主题：标题栏暗色 + 深蓝边框；
    • 不强制 Mica（Mica 会让标题栏变黑，与"淡蓝"诉求冲突）。
    """
    try:
        import pywinstyles
    except ImportError:
        return False
    try:
        if dark is None:
            dark = is_dark()
        if dark:
            header = ACCENT_TITLE_DARK
            border = ACCENT_BORDER_DARK
            title = "#FFFFFF"
        else:
            header = ACCENT_TITLE
            border = ACCENT_BORDER
            title = "#1A1A1A"
        try:
            pywinstyles.change_header_color(window, header)
        except Exception:
            pass
        try:
            pywinstyles.change_border_color(window, border)
        except Exception:
            pass
        try:
            pywinstyles.change_title_color(window, title)
        except Exception:
            pass
        return True
    except Exception:
        return False


# 保留旧名以兼容老调用
def apply_mica(window, dark: bool | None = None) -> bool:
    return apply_window_chrome(window, dark)


def apply_acrylic(window) -> bool:
    try:
        import pywinstyles
        pywinstyles.apply_style(window, "acrylic")
        return True
    except Exception:
        return False


def apply_theme(mode: str = "system", color: str = "blue"):
    """全局主题切换。"""
    ctk.set_appearance_mode(mode)
    ctk.set_default_color_theme(color)
