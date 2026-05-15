"""Agent action registry and lightweight intent parsing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable


ActionHandler = Callable[[dict], str]


@dataclass
class AgentAction:
    name: str
    description: str
    handler: ActionHandler
    required_params: tuple[str, ...] = ()


@dataclass
class AgentIntent:
    action: str
    params: dict = field(default_factory=dict)


class AgentActionRegistry:
    """Registry for low-risk UI actions exposed to the Agent."""

    def __init__(self):
        self._actions: dict[str, AgentAction] = {}

    def register(
        self,
        name: str,
        description: str,
        handler: ActionHandler,
        *,
        required_params: tuple[str, ...] = (),
    ):
        self._actions[name] = AgentAction(
            name=name,
            description=description,
            handler=handler,
            required_params=required_params,
        )

    def list_actions(self) -> list[AgentAction]:
        return list(self._actions.values())

    def parse_intent(self, text: str) -> AgentIntent | None:
        return self._parse_json_intent(text) or self._parse_text_intent(text)

    def parse_tool_plan(self, text: str) -> dict[str, Any] | None:
        data = self._extract_json_object(text)
        if not isinstance(data, dict):
            return None
        answer = str(data.get("answer", "")).strip()
        raw_calls = data.get("tool_calls")
        if raw_calls is None and data.get("action"):
            raw_calls = [{"action": data.get("action"), "params": data.get("params", {})}]
        calls = []
        if isinstance(raw_calls, list):
            for item in raw_calls:
                if not isinstance(item, dict):
                    continue
                action = str(item.get("action", "")).strip()
                if not action:
                    continue
                params = item.get("params", {})
                calls.append({
                    "action": action,
                    "params": params if isinstance(params, dict) else {},
                })
        if not answer and not calls:
            return None
        return {"answer": answer, "tool_calls": calls}

    def execute(self, intent: AgentIntent) -> str:
        action = self._actions.get(intent.action)
        if action is None:
            return f"未注册动作: {intent.action}"
        missing = [
            key for key in action.required_params
            if not str(intent.params.get(key, "")).strip()
        ]
        if missing:
            return f"缺少必要参数: {', '.join(missing)}"
        return action.handler(intent.params)

    def _parse_json_intent(self, text: str) -> AgentIntent | None:
        data = self._extract_json_object(text)
        if not isinstance(data, dict):
            return None
        action = str(data.get("action", "")).strip()
        if not action:
            return None
        params = data.get("params", {})
        return AgentIntent(action=action, params=params if isinstance(params, dict) else {})

    def _extract_json_object(self, text: str) -> Any:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        decoder = json.JSONDecoder()
        start = cleaned.find("{")
        while start >= 0:
            try:
                data, _end = decoder.raw_decode(cleaned[start:])
                return data
            except json.JSONDecodeError:
                start = cleaned.find("{", start + 1)
        return None

    def _parse_text_intent(self, text: str) -> AgentIntent | None:
        compact = re.sub(r"\s+", "", text.strip().lower())
        if not compact:
            return None

        if compact in {"状态", "当前状态", "任务状态"} or any(
            word in compact for word in ("现在在运行什么", "有哪些任务", "任务情况")
        ):
            return AgentIntent("app.status")

        if any(word in compact for word in ("切到贴吧", "打开贴吧", "贴吧页面")):
            return AgentIntent("app.switch_tab", {"tab": "tieba"})
        if any(word in compact for word in ("切到抢票", "打开抢票", "抢票页面", "票务页面")):
            return AgentIntent("app.switch_tab", {"tab": "ticket"})
        if "大麦" in compact and any(word in compact for word in ("页面", "打开", "切到")):
            return AgentIntent("app.switch_tab", {"tab": "damai"})
        if "12306" in compact and any(word in compact for word in ("页面", "打开", "切到")):
            return AgentIntent("app.switch_tab", {"tab": "12306"})

        if any(word in compact for word in ("停止签到", "中止签到")):
            return AgentIntent("tieba.stop")
        if any(word in compact for word in ("一键签到", "全部签到")):
            return AgentIntent("tieba.sign_all")
        if any(word in compact for word in ("逐个签到", "普通签到")):
            return AgentIntent("tieba.sign_normal")

        if "12306" in compact and any(word in compact for word in ("停止", "中止")):
            return AgentIntent("ticket.stop_polling")
        if "大麦" in compact and any(word in compact for word in ("停止", "中止")):
            return AgentIntent("damai.stop_polling")

        ticket_params = self._parse_ticket_params(text)
        if ticket_params and any(word in compact for word in ("查票", "余票", "抢票", "轮询")):
            return AgentIntent("ticket.start_polling", ticket_params)

        damai_params = self._parse_damai_params(text)
        if ("大麦" in compact or damai_params) and any(
            word in compact for word in ("查库存", "库存", "查票", "余票", "轮询", "开始")
        ):
            return AgentIntent("damai.query_stock", damai_params)

        return None

    def _parse_ticket_params(self, text: str) -> dict:
        params: dict[str, str] = {}
        match = re.search(r"从(?P<from>[\u4e00-\u9fa5A-Za-z]+?)(?:到|去)(?P<to>[\u4e00-\u9fa5A-Za-z]+)", text)
        if match:
            params["from"] = self._clean_station_name(match.group("from"))
            params["to"] = self._clean_station_name(match.group("to"))
        else:
            cleaned = text
            for word in (
                "帮我", "请", "查一下", "查询", "查", "今天", "明天", "后天",
                "余票", "车票", "火车票", "高铁", "动车", "二等座", "一等座",
                "商务座", "硬卧", "硬座", "软卧", "无座", "的",
            ):
                cleaned = cleaned.replace(word, "")
            match = re.search(r"(?P<from>[\u4e00-\u9fa5A-Za-z]{2,8})(?:到|去)(?P<to>[\u4e00-\u9fa5A-Za-z]{2,8})", cleaned)
            if match:
                params["from"] = self._clean_station_name(match.group("from"))
                params["to"] = self._clean_station_name(match.group("to"))
        date = self._parse_date(text)
        if date:
            params["date"] = date
        seat = self._parse_seat(text)
        if seat:
            params["seat"] = seat
        return params

    def _clean_station_name(self, value: str) -> str:
        cleaned = value.strip()
        for word in (
            "今天", "明天", "后天", "余票", "车票", "火车票", "高铁", "动车",
            "二等座", "一等座", "商务座", "硬卧", "硬座", "软卧", "无座",
        ):
            cleaned = cleaned.replace(word, "")
        return cleaned.strip()

    def _parse_damai_params(self, text: str) -> dict:
        params: dict[str, str] = {}
        match = re.search(r"(https?://\S+|\b\d{6,}\b)", text)
        if match:
            params["url_or_id"] = match.group(1).rstrip("，。,.;；")
        return params

    def _parse_date(self, text: str) -> str:
        now = datetime.now()
        if "后天" in text:
            return (now + timedelta(days=2)).strftime("%Y-%m-%d")
        if "明天" in text:
            return (now + timedelta(days=1)).strftime("%Y-%m-%d")
        if "今天" in text:
            return now.strftime("%Y-%m-%d")
        match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
        if match:
            y, m, d = (int(part) for part in match.groups())
            return f"{y:04d}-{m:02d}-{d:02d}"
        match = re.search(r"(\d{1,2})月(\d{1,2})日", text)
        if match:
            m, d = (int(part) for part in match.groups())
            return f"{now.year:04d}-{m:02d}-{d:02d}"
        return ""

    def _parse_seat(self, text: str) -> str:
        seats = [
            "商务座", "特等座", "一等座", "二等座", "高级软卧", "软卧",
            "动卧", "硬卧", "软座", "硬座", "无座",
        ]
        for seat in seats:
            if seat in text:
                return seat
        return ""
