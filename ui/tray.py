"""系统托盘图标封装。"""

import threading
from typing import Callable

import pystray
from PIL import Image, ImageDraw, ImageFont


def create_tray_image() -> Image.Image:
    """生成一个简单的托盘图标（蓝底白字 "签"）。"""
    size = 64
    img = Image.new("RGBA", (size, size), (30, 144, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("msyh.ttc", 36)
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "签", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
        "签",
        fill="white",
        font=font,
    )
    return img


class TrayManager:
    """托盘图标管理：首次显示时创建、再次显示时复用。"""

    def __init__(self, title: str, on_show: Callable, on_quit: Callable):
        self._title = title
        self._on_show = on_show
        self._on_quit = on_quit
        self._icon: pystray.Icon | None = None

    def show(self):
        if self._icon is None:
            menu = pystray.Menu(
                pystray.MenuItem("显示", self._on_show, default=True),
                pystray.MenuItem("退出", self._on_quit),
            )
            self._icon = pystray.Icon(
                "BaiduTiebaSign",
                create_tray_image(),
                self._title,
                menu,
            )
            threading.Thread(target=self._icon.run, daemon=True).start()
        else:
            self._icon.visible = True

    def stop(self):
        if self._icon:
            self._icon.stop()
            self._icon = None
