"""Ollama model chat tab."""

from __future__ import annotations

import base64
import io
import json
import re
import threading
import tkinter as tk
from tkinter import messagebox
from urllib.parse import urlparse

import customtkinter as ctk
import requests
from PIL import Image, ImageTk

from . import styling as S
from .widgets import (
    SectionCard,
    accent_button,
    danger_button,
    standard_button,
    subtle_button,
)


DEFAULT_OLLAMA_URL = "http://localhost:11434"
EMPTY_MODEL_TEXT = "请先刷新模型"
NO_MODEL_TEXT = "没有本地模型"
PROVIDER_OLLAMA = "Ollama"
PROVIDER_OTHER = "其他"
IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


class OllamaTab(ctk.CTkFrame):
    """A small Ollama client that can switch between multiple API endpoints."""

    def __init__(self, parent, *, config_data: dict, on_save, compact: bool = False):
        super().__init__(parent, fg_color="transparent")
        self._config_data = config_data
        self._on_save = on_save
        self._compact = compact
        self._models: list[str] = []
        self._histories: dict[str, list[dict[str, str]]] = {}
        self._chat_images: list[ImageTk.PhotoImage] = []
        self._sending = False

        self._ensure_endpoint_config()
        self._build()
        self._load_endpoint_to_ui()
        self.after(200, self.refresh_models)

    def _build(self):
        if self._compact:
            self._build_compact()
            return

        pad = {"padx": S.SPACE_MD, "pady": S.SPACE_SM}

        conn_card = SectionCard(self, title="大模型服务")
        conn_card.pack(fill="x", **pad)
        conn = conn_card.body
        conn.columnconfigure(1, weight=1)
        conn.columnconfigure(4, weight=2)

        ctk.CTkLabel(
            conn,
            text="类型",
            font=S.font_body(),
            text_color=S.TEXT_SECONDARY,
        ).grid(row=0, column=0, sticky="w", padx=(0, S.SPACE_SM))

        self._provider_var = tk.StringVar(value=PROVIDER_OLLAMA)
        self._provider_menu = ctk.CTkOptionMenu(
            conn,
            variable=self._provider_var,
            values=[PROVIDER_OLLAMA, PROVIDER_OTHER],
            command=self._on_provider_selected,
            width=120,
            height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            fg_color=S.LAYER_ALT,
            button_color=S.accent_pair(),
            button_hover_color=S.accent_hover_pair(),
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
        )
        self._provider_menu.grid(row=0, column=1, sticky="w", padx=(0, S.SPACE_MD))

        ctk.CTkLabel(
            conn,
            text="地址",
            font=S.font_body(),
            text_color=S.TEXT_SECONDARY,
        ).grid(row=0, column=2, sticky="w", padx=(0, S.SPACE_SM))

        self._endpoint_var = tk.StringVar()
        self._endpoint_menu = ctk.CTkOptionMenu(
            conn,
            variable=self._endpoint_var,
            values=["本机 Ollama"],
            command=self._on_endpoint_selected,
            width=190,
            height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            fg_color=S.LAYER_ALT,
            button_color=S.accent_pair(),
            button_hover_color=S.accent_hover_pair(),
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
        )
        self._endpoint_menu.grid(row=0, column=3, sticky="w", padx=(0, S.SPACE_SM))

        self._refresh_btn = standard_button(
            conn,
            "刷新模型",
            self.refresh_models,
            width=86,
        )
        self._refresh_btn.grid(row=0, column=4, sticky="w", padx=(0, S.SPACE_SM))

        self._status_var = tk.StringVar(value="未连接")
        ctk.CTkLabel(
            conn,
            textvariable=self._status_var,
            font=S.font_body(),
            text_color=S.TEXT_SECONDARY,
            width=120,
            anchor="e",
        ).grid(row=0, column=5, columnspan=2, sticky="e")

        ctk.CTkLabel(
            conn,
            text="名称",
            font=S.font_body(),
            text_color=S.TEXT_SECONDARY,
        ).grid(row=1, column=0, sticky="w", padx=(0, S.SPACE_SM), pady=(S.SPACE_SM, 0))

        self._endpoint_name_var = tk.StringVar()
        self._name_entry = ctk.CTkEntry(
            conn,
            textvariable=self._endpoint_name_var,
            width=140,
            height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
            placeholder_text="名称",
        )
        self._name_entry.grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, S.SPACE_SM),
            pady=(S.SPACE_SM, 0),
        )

        ctk.CTkLabel(
            conn,
            text="链接",
            font=S.font_body(),
            text_color=S.TEXT_SECONDARY,
        ).grid(row=1, column=2, sticky="w", padx=(0, S.SPACE_SM), pady=(S.SPACE_SM, 0))

        self._base_url = tk.StringVar()
        self._url_entry = ctk.CTkEntry(
            conn,
            textvariable=self._base_url,
            height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
            placeholder_text="http://群晖IP:11434",
        )
        self._url_entry.grid(
            row=1,
            column=3,
            columnspan=2,
            sticky="ew",
            padx=(0, S.SPACE_SM),
            pady=(S.SPACE_SM, 0),
        )

        standard_button(
            conn,
            "保存地址",
            self._save_endpoint,
            width=86,
        ).grid(row=1, column=5, padx=(0, S.SPACE_SM), pady=(S.SPACE_SM, 0))

        danger_button(
            conn,
            "删除",
            self._delete_endpoint,
            width=58,
            height=S.INPUT_HEIGHT,
        ).grid(row=1, column=6, padx=(0, S.SPACE_SM), pady=(S.SPACE_SM, 0))

        model_bar = ctk.CTkFrame(self, fg_color="transparent")
        model_bar.pack(fill="x", **pad)
        ctk.CTkLabel(
            model_bar,
            text="模型",
            font=S.font_body(),
            text_color=S.TEXT_SECONDARY,
        ).pack(side="left", padx=(0, S.SPACE_SM))

        self._model_var = tk.StringVar(value="")
        self._model_menu = ctk.CTkOptionMenu(
            model_bar,
            variable=self._model_var,
            values=[EMPTY_MODEL_TEXT],
            command=self._on_model_selected,
            width=260,
            height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            fg_color=S.LAYER_ALT,
            button_color=S.accent_pair(),
            button_hover_color=S.accent_hover_pair(),
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
        )
        self._model_menu.pack(side="left")
        self._model_name_var = tk.StringVar(value="")
        self._model_entry = ctk.CTkEntry(
            model_bar,
            textvariable=self._model_name_var,
            width=220,
            height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
            placeholder_text="其他服务可手动输入模型名",
        )
        self._model_entry.pack(side="left", padx=(S.SPACE_SM, 0))

        subtle_button(
            model_bar,
            "清空当前对话",
            self._clear_current_chat,
            width=110,
        ).pack(side="right")

        chat_card = SectionCard(self, title="对话")
        chat_card.pack(fill="both", expand=True, **pad)
        self._chat_area = ctk.CTkScrollableFrame(
            chat_card.body,
            height=360,
            corner_radius=S.RADIUS_INPUT,
            border_width=1,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
        )
        self._chat_area.pack(fill="both", expand=True)

        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x", **pad)
        input_frame.columnconfigure(0, weight=1)

        self._input = ctk.CTkTextbox(
            input_frame,
            height=86,
            wrap="word",
            corner_radius=S.RADIUS_INPUT,
            border_width=1,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(13),
        )
        self._input.grid(row=0, column=0, sticky="ew", padx=(0, S.SPACE_SM))
        self._input.bind("<Return>", self._on_input_return)
        self._input.bind("<Control-Return>", self._on_input_ctrl_return)

        send_tools = ctk.CTkFrame(input_frame, fg_color="transparent")
        send_tools.grid(row=0, column=1, sticky="ns")

        self._send_shortcut_var = tk.StringVar(
            value=self._shortcut_label(
                self._config_data.get("ollama_send_shortcut", "enter")
            )
        )
        self._send_shortcut_menu = ctk.CTkOptionMenu(
            send_tools,
            variable=self._send_shortcut_var,
            values=["Enter发送", "Ctrl+Enter发送"],
            command=self._on_send_shortcut_changed,
            width=116,
            height=30,
            corner_radius=S.RADIUS_INPUT,
            fg_color=S.LAYER_ALT,
            button_color=S.accent_pair(),
            button_hover_color=S.accent_hover_pair(),
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(12),
        )
        self._send_shortcut_menu.pack(fill="x", pady=(0, S.SPACE_SM))
        self._send_btn = accent_button(
            send_tools,
            "发送",
            self._send_message,
            width=116,
            height=48,
        )
        self._send_btn.pack(fill="both", expand=True)

    def _build_compact(self):
        pad = {"padx": S.SPACE_SM, "pady": S.SPACE_XS}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        topbar = ctk.CTkFrame(self, fg_color="transparent", height=38)
        topbar.grid(row=0, column=0, sticky="ew", **pad)
        topbar.grid_columnconfigure(1, weight=1)
        topbar.grid_propagate(False)

        standard_button(
            topbar,
            "Agent 设置",
            self._open_agent_settings,
            width=96,
            height=30,
        ).grid(row=0, column=0, sticky="w", padx=(0, S.SPACE_SM))

        self._model_var = tk.StringVar(value="")
        self._model_menu = ctk.CTkOptionMenu(
            topbar,
            variable=self._model_var,
            values=[EMPTY_MODEL_TEXT],
            command=self._on_model_selected,
            height=30,
            corner_radius=S.RADIUS_INPUT,
            fg_color=S.LAYER_ALT,
            button_color=S.accent_pair(),
            button_hover_color=S.accent_hover_pair(),
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
        )
        self._model_menu.grid(row=0, column=1, sticky="ew")

        self._refresh_btn = subtle_button(
            topbar,
            "刷新",
            self.refresh_models,
            width=48,
            height=30,
        )
        self._refresh_btn.grid(row=0, column=2, sticky="e", padx=(S.SPACE_SM, 0))

        self._provider_var = tk.StringVar(value=PROVIDER_OLLAMA)
        self._endpoint_var = tk.StringVar()
        self._endpoint_name_var = tk.StringVar()
        self._base_url = tk.StringVar()
        self._model_name_var = tk.StringVar(value="")
        self._status_var = tk.StringVar(value="未连接")
        self._settings_window: ctk.CTkToplevel | None = None
        self._settings_model_menu: ctk.CTkOptionMenu | None = None
        self._endpoint_menu: ctk.CTkOptionMenu | None = None

        chat_card = SectionCard(self, title="对话", body_padx=S.SPACE_MD)
        chat_card.grid(row=1, column=0, sticky="nsew", **pad)
        self._chat_area = ctk.CTkScrollableFrame(
            chat_card.body,
            height=320,
            corner_radius=S.RADIUS_INPUT,
            border_width=1,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
        )
        self._chat_area.pack(fill="both", expand=True)

        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.grid(row=2, column=0, sticky="ew", **pad)
        input_frame.columnconfigure(0, weight=1)

        self._input = ctk.CTkTextbox(
            input_frame,
            height=74,
            wrap="word",
            corner_radius=S.RADIUS_INPUT,
            border_width=1,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(13),
        )
        self._input.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._input.bind("<Return>", self._on_input_return)
        self._input.bind("<Control-Return>", self._on_input_ctrl_return)

        self._send_shortcut_var = tk.StringVar(
            value=self._shortcut_label(
                self._config_data.get("ollama_send_shortcut", "enter")
            )
        )
        self._send_shortcut_menu = ctk.CTkOptionMenu(
            input_frame,
            variable=self._send_shortcut_var,
            values=["Enter发送", "Ctrl+Enter发送"],
            command=self._on_send_shortcut_changed,
            width=116,
            height=30,
            corner_radius=S.RADIUS_INPUT,
            fg_color=S.LAYER_ALT,
            button_color=S.accent_pair(),
            button_hover_color=S.accent_hover_pair(),
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(12),
        )
        self._send_shortcut_menu.grid(
            row=1, column=0, sticky="w", pady=(S.SPACE_SM, 0)
        )
        self._send_btn = accent_button(
            input_frame,
            "发送",
            self._send_message,
            width=86,
            height=30,
        )
        self._send_btn.grid(row=1, column=1, sticky="e", pady=(S.SPACE_SM, 0))

    def _open_agent_settings(self):
        if self._settings_window is not None:
            try:
                self._settings_window.lift()
                self._settings_window.focus_force()
                return
            except tk.TclError:
                self._settings_window = None

        win = ctk.CTkToplevel(self)
        self._settings_window = win
        win.title("Agent 设置")
        win.transient(self.winfo_toplevel())
        win.geometry("980x680")
        win.minsize(860, 580)
        win.configure(fg_color=S.WIN_BG)
        win.columnconfigure(0, weight=1)
        win.columnconfigure(1, weight=1)
        win.rowconfigure(1, weight=1)

        header = ctk.CTkFrame(win, fg_color="transparent", height=42)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=S.SPACE_LG, pady=(S.SPACE_MD, 0))
        header.grid_columnconfigure(1, weight=1)
        header.grid_propagate(False)

        ctk.CTkLabel(
            header,
            text="Agent 设置",
            font=S.font_title(S.TITLE),
            text_color=S.TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            textvariable=self._status_var,
            font=S.font_body(),
            text_color=S.TEXT_SECONDARY,
        ).grid(row=0, column=1, sticky="e", padx=(0, S.SPACE_SM))
        accent_button(
            header,
            "完成",
            self._close_agent_settings,
            width=72,
            height=30,
        ).grid(row=0, column=2, sticky="e")

        edit = ctk.CTkScrollableFrame(win, fg_color="transparent")
        edit.grid(row=1, column=0, sticky="nsew", padx=(S.SPACE_LG, S.SPACE_SM), pady=S.SPACE_MD)
        preview = ctk.CTkFrame(
            win,
            corner_radius=S.RADIUS_CARD,
            border_width=1,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER,
        )
        preview.grid(row=1, column=1, sticky="nsew", padx=(S.SPACE_SM, S.SPACE_LG), pady=S.SPACE_MD)
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(1, weight=1)

        self._build_agent_prompt_card(edit)
        self._build_agent_model_card(edit)
        self._build_agent_placeholder_card(
            edit,
            "知识库",
            "装配工艺知识库尚未接入。后续可在这里添加工艺文档、标准规范、工艺卡、设备说明和常见问题。",
        )
        self._build_agent_placeholder_card(
            edit,
            "工具",
            "后续可把贴吧签到、余票查询、开始轮询、停止任务等能力注册为 Agent 可调用工具。",
        )

        ctk.CTkLabel(
            preview,
            text="调试与预览",
            font=S.font_strong(),
            text_color=S.TEXT_PRIMARY,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=S.SPACE_LG, pady=(S.SPACE_LG, S.SPACE_SM))
        ctk.CTkLabel(
            preview,
            text="设置保存后，可回到右侧 Agent 抽屉中直接对话调试。",
            font=S.font_body(),
            text_color=S.TEXT_SECONDARY,
            anchor="nw",
            justify="left",
            wraplength=420,
        ).grid(row=1, column=0, sticky="nsew", padx=S.SPACE_LG, pady=S.SPACE_SM)
        bottom = ctk.CTkFrame(preview, fg_color=S.LAYER_ALT, corner_radius=S.RADIUS_INPUT)
        bottom.grid(row=2, column=0, sticky="ew", padx=S.SPACE_LG, pady=(S.SPACE_SM, S.SPACE_LG))
        bottom.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            bottom,
            text="和 Bot 聊天",
            font=S.font_body(),
            text_color=S.TEXT_TERTIARY,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=S.SPACE_MD, pady=S.SPACE_SM)
        accent_button(
            bottom,
            "发送",
            lambda: None,
            width=58,
            height=30,
        ).grid(row=0, column=1, sticky="e", padx=S.SPACE_SM, pady=S.SPACE_SM)

        win.protocol("WM_DELETE_WINDOW", self._close_agent_settings)
        self._load_endpoint_to_ui()
        self._refresh_settings_model_menu()
        self.after(50, lambda: S.apply_window_chrome(win))

    def _close_agent_settings(self):
        if self._settings_window is not None:
            try:
                self._settings_window.destroy()
            except tk.TclError:
                pass
        self._settings_window = None
        self._settings_model_menu = None
        self._endpoint_menu = None

    def _build_agent_prompt_card(self, parent):
        card = SectionCard(parent, title="提示词")
        card.pack(fill="x", padx=S.SPACE_SM, pady=S.SPACE_SM)
        prompt = ctk.CTkTextbox(
            card.body,
            height=160,
            wrap="word",
            corner_radius=S.RADIUS_INPUT,
            border_width=1,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
        )
        prompt.pack(fill="x")
        default_prompt = (
            "你是桌面助手，负责协助用户完成贴吧签到、票务查询和本地大模型问答。\n"
            "回答要准确、简洁；涉及执行操作时，先确认必要参数和风险。"
        )
        prompt.insert("1.0", self._config_data.get("agent_prompt", default_prompt))

        def _save_prompt(_event=None):
            self._config_data["agent_prompt"] = prompt.get("1.0", "end").strip()
            self._on_save()

        prompt.bind("<FocusOut>", _save_prompt)

    def _build_agent_model_card(self, parent):
        card = SectionCard(parent, title="模型配置")
        card.pack(fill="x", padx=S.SPACE_SM, pady=S.SPACE_SM)
        body = card.body
        body.columnconfigure(1, weight=1)

        ctk.CTkLabel(body, text="类型", font=S.font_body(), text_color=S.TEXT_SECONDARY).grid(
            row=0, column=0, sticky="w", padx=(0, S.SPACE_SM)
        )
        self._provider_menu = ctk.CTkOptionMenu(
            body,
            variable=self._provider_var,
            values=[PROVIDER_OLLAMA, PROVIDER_OTHER],
            command=self._on_provider_selected,
            height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            fg_color=S.LAYER_ALT,
            button_color=S.accent_pair(),
            button_hover_color=S.accent_hover_pair(),
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
        )
        self._provider_menu.grid(row=0, column=1, sticky="ew")

        ctk.CTkLabel(body, text="地址", font=S.font_body(), text_color=S.TEXT_SECONDARY).grid(
            row=1, column=0, sticky="w", padx=(0, S.SPACE_SM), pady=(S.SPACE_SM, 0)
        )

        self._endpoint_menu = ctk.CTkOptionMenu(
            body,
            variable=self._endpoint_var,
            values=["本机 Ollama"],
            command=self._on_endpoint_selected,
            height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            fg_color=S.LAYER_ALT,
            button_color=S.accent_pair(),
            button_hover_color=S.accent_hover_pair(),
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
        )
        self._endpoint_menu.grid(row=1, column=1, sticky="ew", pady=(S.SPACE_SM, 0))

        tools = ctk.CTkFrame(body, fg_color="transparent")
        tools.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(S.SPACE_SM, 0))
        tools.columnconfigure(1, weight=1)

        standard_button(
            tools,
            "刷新模型",
            self.refresh_models,
            width=86,
        ).grid(row=0, column=0, sticky="w", padx=(0, S.SPACE_SM))

        ctk.CTkLabel(
            tools,
            textvariable=self._status_var,
            font=S.font_body(),
            text_color=S.TEXT_SECONDARY,
            anchor="e",
        ).grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(body, text="名称", font=S.font_body(), text_color=S.TEXT_SECONDARY).grid(
            row=3, column=0, sticky="w", padx=(0, S.SPACE_SM), pady=(S.SPACE_SM, 0)
        )

        self._name_entry = ctk.CTkEntry(
            body,
            textvariable=self._endpoint_name_var,
            height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
            placeholder_text="名称",
        )
        self._name_entry.grid(row=3, column=1, sticky="ew", pady=(S.SPACE_SM, 0))

        ctk.CTkLabel(body, text="链接", font=S.font_body(), text_color=S.TEXT_SECONDARY).grid(
            row=4, column=0, sticky="w", padx=(0, S.SPACE_SM), pady=(S.SPACE_SM, 0)
        )

        self._url_entry = ctk.CTkEntry(
            body,
            textvariable=self._base_url,
            height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
            placeholder_text="http://localhost:11434",
        )
        self._url_entry.grid(row=4, column=1, sticky="ew", pady=(S.SPACE_SM, 0))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(S.SPACE_SM, 0))
        standard_button(
            actions,
            "保存地址",
            self._save_endpoint,
            width=86,
        ).pack(side="left", padx=(0, S.SPACE_SM))
        danger_button(
            actions,
            "删除",
            self._delete_endpoint,
            width=58,
            height=S.INPUT_HEIGHT,
        ).pack(side="left")

        ctk.CTkLabel(body, text="模型", font=S.font_body(), text_color=S.TEXT_SECONDARY).grid(
            row=6, column=0, sticky="w", padx=(0, S.SPACE_SM), pady=(S.SPACE_MD, 0)
        )

        self._settings_model_menu = ctk.CTkOptionMenu(
            body,
            variable=self._model_var,
            values=[EMPTY_MODEL_TEXT],
            command=self._on_model_selected,
            height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            fg_color=S.LAYER_ALT,
            button_color=S.accent_pair(),
            button_hover_color=S.accent_hover_pair(),
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
        )
        self._settings_model_menu.grid(row=6, column=1, sticky="ew", pady=(S.SPACE_MD, 0))

        self._model_entry = ctk.CTkEntry(
            body,
            textvariable=self._model_name_var,
            height=S.INPUT_HEIGHT,
            corner_radius=S.RADIUS_INPUT,
            border_color=S.LAYER_BORDER,
            fg_color=S.LAYER_ALT,
            text_color=S.TEXT_PRIMARY,
            font=S.font_body(),
            placeholder_text="可手动输入模型名",
        )
        self._model_entry.grid(row=7, column=1, sticky="ew", pady=(S.SPACE_SM, 0))

    def _build_agent_placeholder_card(self, parent, title: str, message: str):
        card = SectionCard(parent, title=title)
        card.pack(fill="x", padx=S.SPACE_SM, pady=S.SPACE_SM)
        ctk.CTkLabel(
            card.body,
            text=message,
            font=S.font_body(),
            text_color=S.TEXT_SECONDARY,
            anchor="w",
            justify="left",
            wraplength=420,
        ).pack(fill="x")

    def refresh_models(self):
        self._save_current_endpoint_selection()
        self._refresh_btn.configure(state="disabled")
        self._status_var.set("连接中...")
        provider = self._provider_var.get()

        def _work():
            try:
                if provider == PROVIDER_OLLAMA:
                    models = self._fetch_ollama_models()
                else:
                    models = self._fetch_openai_models()
                self._ui(self._set_models, models)
            except Exception as e:
                self._ui(self._set_error, f"{type(e).__name__}: {e}")
            finally:
                self._ui(self._refresh_btn.configure, state="normal")

        threading.Thread(target=_work, daemon=True).start()

    def _fetch_ollama_models(self) -> list[str]:
        resp = requests.get(self._url("/api/tags"), timeout=8)
        resp.raise_for_status()
        data = resp.json()
        return [
            item.get("name", "")
            for item in data.get("models", [])
            if item.get("name")
        ]

    def _fetch_openai_models(self) -> list[str]:
        resp = requests.get(self._url("/v1/models"), timeout=8)
        resp.raise_for_status()
        data = resp.json()
        return [
            item.get("id", "")
            for item in data.get("data", [])
            if item.get("id")
        ]

    def _set_models(self, models: list[str]):
        self._models = models
        if not models:
            self._model_menu.configure(values=[NO_MODEL_TEXT])
            self._refresh_settings_model_menu([NO_MODEL_TEXT])
            self._model_var.set(NO_MODEL_TEXT)
            self._model_name_var.set("")
            self._status_var.set("0 个模型")
            if self._provider_var.get() == PROVIDER_OLLAMA:
                self._render_text("没有找到模型。请先在该地址中运行: ollama pull qwen2.5:3b")
            else:
                self._render_text("没有读取到模型列表。其他服务可以在模型输入框中手动填写模型名。")
            return

        self._model_menu.configure(values=models)
        self._refresh_settings_model_menu(models)
        current = self._model_var.get()
        if current not in models:
            self._model_var.set(models[0])
            self._model_name_var.set(models[0])
        self._status_var.set(f"{len(models)} 个模型")
        self._render_history()

    def _set_error(self, message: str):
        self._models = []
        self._model_menu.configure(values=[EMPTY_MODEL_TEXT])
        self._refresh_settings_model_menu([EMPTY_MODEL_TEXT])
        self._model_var.set(EMPTY_MODEL_TEXT)
        self._model_name_var.set("")
        self._status_var.set("连接失败")
        self._render_text(
            "无法连接当前模型服务。\n\n"
            f"{message}\n\n"
            "Ollama 会从该链接的 /api/tags 获取模型；其他服务会尝试 /v1/models。"
        )

    def _send_message(self):
        if self._sending:
            return
        self._save_current_endpoint_selection()
        model = self._current_model_name()
        if not model or model in {EMPTY_MODEL_TEXT, NO_MODEL_TEXT}:
            messagebox.showwarning("提示", "请先刷新并选择一个模型")
            return

        content = self._input.get("1.0", "end").strip()
        if not content:
            return

        self._input.delete("1.0", "end")
        history_key = self._history_key(model)
        history = self._histories.setdefault(history_key, [])
        history.append({"role": "user", "content": content})
        request_messages = [item.copy() for item in history]
        history.append({"role": "assistant", "content": "生成中..."})
        self._render_history()
        self._set_sending(True)

        def _work():
            try:
                if self._provider_var.get() == PROVIDER_OLLAMA:
                    answer = self._chat_ollama(model, request_messages, history_key)
                else:
                    answer = self._chat_openai(model, request_messages)
                if not answer:
                    answer = "(模型没有返回内容)"
                self._ui(self._replace_answer, history_key, answer)
            except Exception as e:
                self._ui(
                    self._replace_answer,
                    history_key,
                    f"[请求失败] {type(e).__name__}: {e}",
                )
            finally:
                self._ui(self._set_sending, False)

        threading.Thread(target=_work, daemon=True).start()

    def _chat_ollama(
        self,
        model: str,
        history: list[dict[str, str]],
        history_key: str,
    ) -> str:
        resp = requests.post(
            self._url("/api/chat"),
            json={
                "model": model,
                "messages": history,
                "stream": True,
            },
            stream=True,
            timeout=(10, 600),
        )
        resp.raise_for_status()
        chunks: list[str] = []
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            data = json.loads(line)
            part = data.get("message", {}).get("content", "")
            if part:
                chunks.append(part)
                self._ui(self._replace_answer, history_key, "".join(chunks))
            if data.get("done"):
                break
        return "".join(chunks).strip()

    def _chat_openai(self, model: str, history: list[dict[str, str]]) -> str:
        resp = requests.post(
            self._url("/v1/chat/completions"),
            json={
                "model": model,
                "messages": history,
                "stream": False,
            },
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "").strip()

    def _replace_answer(self, history_key: str, answer: str):
        history = self._histories.setdefault(history_key, [])
        if history and history[-1].get("role") == "assistant":
            history[-1]["content"] = answer
        else:
            history.append({"role": "assistant", "content": answer})
        if self._history_key(self._current_model_name()) == history_key:
            self._render_history()

    def _clear_current_chat(self):
        model = self._current_model_name()
        if model:
            self._histories[self._history_key(model)] = []
        self._render_history()

    def _render_history(self):
        model = self._current_model_name()
        history = self._histories.get(self._history_key(model), [])
        if not history:
            self._render_text("选择地址和模型后即可开始对话。Ctrl+Enter 也可以发送。")
            return

        self._render_messages(history)

    def _render_messages(self, history: list[dict[str, str]]):
        self._clear_chat_area()
        self._chat_images.clear()
        for item in history:
            role = item.get("role")
            content = item.get("content", "").strip()
            if not content:
                continue
            self._add_message_bubble(role or "assistant", content)
        self._scroll_chat_to_bottom()

    def _render_text(self, text: str):
        self._clear_chat_area()
        self._chat_images.clear()
        self._add_message_bubble("assistant", text)
        self._scroll_chat_to_bottom()

    def _clear_chat_area(self):
        for child in self._chat_area.winfo_children():
            child.destroy()

    def _add_message_bubble(self, role: str, content: str):
        is_user = role == "user"
        row = ctk.CTkFrame(self._chat_area, fg_color="transparent")
        row.pack(fill="x", padx=S.SPACE_SM, pady=(S.SPACE_XS, S.SPACE_SM))

        bubble = ctk.CTkFrame(
            row,
            corner_radius=8,
            fg_color=S.accent_pair() if is_user else S.LAYER,
            border_width=0 if is_user else 1,
            border_color=S.LAYER_BORDER,
        )
        side_pad = 28 if self._compact else 120
        bubble.pack(
            side="right" if is_user else "left",
            anchor="e" if is_user else "w",
            padx=(side_pad, 0) if is_user else (0, side_pad),
        )

        if is_user:
            self._add_text_label(bubble, content, is_user=True)
            return
        self._insert_rich_content(bubble, content)

    def _insert_rich_content(self, bubble, content: str):
        blocks = self._split_image_blocks(content)
        for kind, value in blocks:
            if kind == "image":
                if not self._insert_image(bubble, value):
                    self._add_text_label(bubble, f"[图片无法显示] {value}")
                continue
            self._insert_text_with_tables(bubble, value)

    def _split_image_blocks(self, content: str) -> list[tuple[str, str]]:
        blocks: list[tuple[str, str]] = []
        pos = 0
        for match in IMAGE_PATTERN.finditer(content):
            if match.start() > pos:
                blocks.append(("text", content[pos:match.start()]))
            blocks.append(("image", match.group(2).strip()))
            pos = match.end()
        if pos < len(content):
            blocks.append(("text", content[pos:]))
        return blocks

    def _insert_text_with_tables(self, bubble, text: str):
        lines = text.strip("\n").splitlines()
        i = 0
        pending: list[str] = []
        while i < len(lines):
            if self._is_table_start(lines, i):
                if pending:
                    self._add_text_label(bubble, "\n".join(pending).strip())
                    pending = []
                table_lines = []
                while i < len(lines) and "|" in lines[i]:
                    table_lines.append(lines[i])
                    i += 1
                self._add_text_label(
                    bubble,
                    self._format_markdown_table(table_lines),
                    font=S.font_mono(12),
                )
                continue
            pending.append(lines[i])
            i += 1
        if pending:
            self._add_text_label(bubble, "\n".join(pending).strip())

    def _add_text_label(self, parent, text: str, *, is_user: bool = False, font=None):
        if not text:
            return
        ctk.CTkLabel(
            parent,
            text=text,
            justify="left",
            anchor="w",
            wraplength=300 if self._compact else 620,
            font=font or S.font_body(13),
            text_color=S.TEXT_ON_ACCENT if is_user else S.TEXT_PRIMARY,
        ).pack(fill="x", padx=S.SPACE_MD, pady=S.SPACE_SM)

    def _is_table_start(self, lines: list[str], index: int) -> bool:
        if index + 1 >= len(lines):
            return False
        return "|" in lines[index] and self._is_table_separator(lines[index + 1])

    def _is_table_separator(self, line: str) -> bool:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)

    def _format_markdown_table(self, lines: list[str]) -> str:
        rows = [
            [cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in lines
            if not self._is_table_separator(line)
        ]
        if not rows:
            return "\n".join(lines)
        widths = [0] * max(len(row) for row in rows)
        for row in rows:
            for idx, cell in enumerate(row):
                widths[idx] = max(widths[idx], self._display_width(cell))
        rendered = []
        for row_index, row in enumerate(rows):
            padded = [
                self._pad_display(cell, widths[idx])
                for idx, cell in enumerate(row)
            ]
            rendered.append("  ".join(padded))
            if row_index == 0:
                rendered.append("  ".join("-" * width for width in widths))
        return "\n".join(rendered)

    def _display_width(self, text: str) -> int:
        return sum(2 if ord(char) > 127 else 1 for char in text)

    def _pad_display(self, text: str, width: int) -> str:
        return text + " " * max(0, width - self._display_width(text))

    def _insert_image(self, parent, source: str) -> bool:
        try:
            image = self._load_image(source)
            image.thumbnail((300, 220) if self._compact else (520, 320), Image.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self._chat_images.append(photo)
            ctk.CTkLabel(parent, text="", image=photo).pack(
                padx=S.SPACE_MD,
                pady=S.SPACE_SM,
            )
            return True
        except Exception:
            return False

    def _load_image(self, source: str) -> Image.Image:
        if source.startswith("data:image/"):
            encoded = source.split(",", 1)[1]
            return Image.open(io.BytesIO(base64.b64decode(encoded)))
        if source.startswith(("http://", "https://")):
            resp = requests.get(source, timeout=12)
            resp.raise_for_status()
            return Image.open(io.BytesIO(resp.content))
        return Image.open(source)

    def _scroll_chat_to_bottom(self):
        try:
            self._chat_area.update_idletasks()
            canvas = getattr(self._chat_area, "_parent_canvas", None)
            if canvas is not None:
                canvas.yview_moveto(1.0)
        except tk.TclError:
            pass

    def _set_sending(self, sending: bool):
        self._sending = sending
        self._send_btn.configure(state="disabled" if sending else "normal")
        self._status_var.set("生成中..." if sending else f"{len(self._models)} 个模型")

    def _on_input_return(self, event):
        if self._send_shortcut() == "enter" and not self._event_has_shift(event):
            self._send_message()
            return "break"
        return None

    def _on_input_ctrl_return(self, _event):
        if self._send_shortcut() == "ctrl_enter":
            self._send_message()
            return "break"
        self._send_message()
        return "break"

    def _event_has_shift(self, event) -> bool:
        return bool(getattr(event, "state", 0) & 0x0001)

    def _send_shortcut(self) -> str:
        label = self._send_shortcut_var.get()
        return "ctrl_enter" if label.startswith("Ctrl+") else "enter"

    def _shortcut_label(self, value: str) -> str:
        return "Ctrl+Enter发送" if value == "ctrl_enter" else "Enter发送"

    def _on_send_shortcut_changed(self, value: str):
        self._config_data["ollama_send_shortcut"] = (
            "ctrl_enter" if value.startswith("Ctrl+") else "enter"
        )
        self._on_save()

    def _on_model_selected(self, value: str):
        if value not in {EMPTY_MODEL_TEXT, NO_MODEL_TEXT}:
            self._model_name_var.set(value)
        self._render_history()

    def _current_model_name(self) -> str:
        typed = self._model_name_var.get().strip()
        if typed:
            return typed
        return self._model_var.get().strip()

    def _ensure_endpoint_config(self):
        endpoints = self._config_data.get("ollama_endpoints")
        if not isinstance(endpoints, list) or not endpoints:
            endpoints = [
                {"name": "本机 Ollama", "url": DEFAULT_OLLAMA_URL, "provider": PROVIDER_OLLAMA}
            ]
            self._config_data["ollama_endpoints"] = endpoints
        cleaned = []
        seen_urls = set()
        for item in endpoints:
            if not isinstance(item, dict):
                continue
            url = self._normalize_url(str(item.get("url", "")).strip())
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            name = str(item.get("name", "")).strip() or self._name_from_url(url)
            provider = str(item.get("provider", PROVIDER_OLLAMA)).strip()
            if provider not in {PROVIDER_OLLAMA, PROVIDER_OTHER}:
                provider = PROVIDER_OLLAMA
            cleaned.append({"name": name, "url": url, "provider": provider})
        if not cleaned:
            cleaned = [
                {"name": "本机 Ollama", "url": DEFAULT_OLLAMA_URL, "provider": PROVIDER_OLLAMA}
            ]
        self._config_data["ollama_endpoints"] = cleaned
        current = self._normalize_url(
            str(self._config_data.get("ollama_current_endpoint", "")).strip()
        )
        if current not in {item["url"] for item in cleaned}:
            current = cleaned[0]["url"]
        self._config_data["ollama_current_endpoint"] = current

    def _load_endpoint_to_ui(self):
        endpoint = self._current_endpoint()
        self._provider_var.set(endpoint.get("provider", PROVIDER_OLLAMA))
        self._refresh_endpoint_menu()
        self._endpoint_var.set(self._endpoint_label(endpoint))
        self._endpoint_name_var.set(endpoint["name"])
        self._base_url.set(endpoint["url"])

    def _refresh_endpoint_menu(self):
        values = [self._endpoint_label(endpoint) for endpoint in self._filtered_endpoints()]
        if not values:
            values = ["暂无地址"]
        if self._widget_exists(getattr(self, "_endpoint_menu", None)):
            self._endpoint_menu.configure(values=values)

    def _refresh_settings_model_menu(self, values: list[str] | None = None):
        if values is None:
            values = self._models or [EMPTY_MODEL_TEXT]
        if self._widget_exists(getattr(self, "_settings_model_menu", None)):
            self._settings_model_menu.configure(values=values)

    def _widget_exists(self, widget) -> bool:
        if widget is None:
            return False
        try:
            return bool(widget.winfo_exists())
        except tk.TclError:
            return False

    def _on_endpoint_selected(self, label: str):
        endpoint = self._endpoint_by_label(label)
        if endpoint is None:
            return
        self._provider_var.set(endpoint.get("provider", PROVIDER_OLLAMA))
        self._endpoint_name_var.set(endpoint["name"])
        self._base_url.set(endpoint["url"])
        self._config_data["ollama_current_endpoint"] = endpoint["url"]
        self._on_save()
        self._models = []
        self._model_menu.configure(values=[EMPTY_MODEL_TEXT])
        self._refresh_settings_model_menu([EMPTY_MODEL_TEXT])
        self._model_var.set(EMPTY_MODEL_TEXT)
        self._model_name_var.set("")
        self._render_history()
        self.refresh_models()

    def _on_provider_selected(self, provider: str):
        self._config_data["ollama_provider"] = provider
        self._refresh_endpoint_menu()
        endpoints = self._filtered_endpoints()
        if endpoints:
            endpoint = endpoints[0]
            self._endpoint_var.set(self._endpoint_label(endpoint))
            self._endpoint_name_var.set(endpoint["name"])
            self._base_url.set(endpoint["url"])
            self._config_data["ollama_current_endpoint"] = endpoint["url"]
            self._on_save()
            self.refresh_models()
            return

        self._endpoint_var.set("暂无地址")
        self._endpoint_name_var.set("外部服务" if provider == PROVIDER_OTHER else "本机 Ollama")
        self._base_url.set("" if provider == PROVIDER_OTHER else DEFAULT_OLLAMA_URL)
        self._models = []
        self._model_menu.configure(values=[EMPTY_MODEL_TEXT])
        self._refresh_settings_model_menu([EMPTY_MODEL_TEXT])
        self._model_var.set(EMPTY_MODEL_TEXT)
        self._model_name_var.set("")
        self._status_var.set("未连接")
        self._render_text("请填写链接并保存地址，然后刷新模型。")

    def _save_endpoint(self):
        url = self._normalize_url(self._base_url.get())
        if not url:
            messagebox.showwarning("提示", "请输入模型服务地址")
            return
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            messagebox.showwarning("提示", "地址格式应类似 http://192.168.1.10:11434")
            return
        name = self._endpoint_name_var.get().strip() or self._name_from_url(url)
        provider = self._provider_var.get()
        endpoints = self._endpoints()
        for endpoint in endpoints:
            if endpoint["url"] == url:
                endpoint["name"] = name
                endpoint["provider"] = provider
                break
        else:
            endpoints.append({"name": name, "url": url, "provider": provider})
        self._config_data["ollama_endpoints"] = endpoints
        self._config_data["ollama_current_endpoint"] = url
        self._on_save()
        self._load_endpoint_to_ui()
        self.refresh_models()

    def _delete_endpoint(self):
        endpoints = self._endpoints()
        if len(endpoints) <= 1:
            messagebox.showwarning("提示", "至少保留一个模型服务地址")
            return
        url = self._normalize_url(self._base_url.get())
        endpoints = [endpoint for endpoint in endpoints if endpoint["url"] != url]
        self._config_data["ollama_endpoints"] = endpoints
        self._config_data["ollama_current_endpoint"] = endpoints[0]["url"]
        self._on_save()
        self._load_endpoint_to_ui()
        self.refresh_models()

    def _save_current_endpoint_selection(self):
        current = self._normalize_url(self._base_url.get())
        if current:
            self._config_data["ollama_current_endpoint"] = current
        self._config_data["ollama_provider"] = self._provider_var.get()

    def _endpoints(self) -> list[dict[str, str]]:
        return self._config_data.get("ollama_endpoints", [])

    def _filtered_endpoints(self) -> list[dict[str, str]]:
        provider = self._provider_var.get()
        return [
            endpoint
            for endpoint in self._endpoints()
            if endpoint.get("provider", PROVIDER_OLLAMA) == provider
        ]

    def _current_endpoint(self) -> dict[str, str]:
        current_url = self._normalize_url(
            str(self._config_data.get("ollama_current_endpoint", ""))
        )
        for endpoint in self._endpoints():
            if endpoint["url"] == current_url:
                return endpoint
        filtered = self._filtered_endpoints()
        return filtered[0] if filtered else self._endpoints()[0]

    def _endpoint_by_label(self, label: str) -> dict[str, str] | None:
        for endpoint in self._filtered_endpoints():
            if self._endpoint_label(endpoint) == label:
                return endpoint
        return None

    def _endpoint_label(self, endpoint: dict[str, str]) -> str:
        return f"{endpoint['name']} - {endpoint['url']}"

    def _name_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.hostname or "外部 Ollama"

    def _normalize_url(self, url: str) -> str:
        url = url.strip().rstrip("/")
        if not url:
            return ""
        if "://" not in url:
            url = "http://" + url
        return url

    def _history_key(self, model: str) -> str:
        return f"{self._base_url.get().strip().rstrip()}::{model}"

    def _url(self, path: str) -> str:
        return self._normalize_url(self._base_url.get()) + path

    def _ui(self, fn, *args, **kwargs):
        self.after(0, lambda: fn(*args, **kwargs))
