"""12306 自动下单 7 步链（仅个人自购，违反 12306 TOS，账号风险使用者自负）。

任一步遇到风控/滑块/排队失败立即抛异常退出，不重试不绕过。
"""

import datetime as _dt
import random
import re
import time
import urllib.parse
from typing import Callable

from .ticket12306 import BASE_URL

STEP_JITTER = (0.3, 1.0)

# 提交订单用的席别代码（与 leftTicket 列字段名相同但取值不同）
SEAT_TYPE_CODE = {
    "商务座": "9",
    "特等座": "P",
    "一等座": "M",
    "二等座": "O",
    "高级软卧": "6",
    "软卧": "4",
    "动卧": "F",
    "硬卧": "3",
    "软座": "2",
    "硬座": "1",
    "无座": "1",
}


class OrderError(RuntimeError):
    """下单流程中可控的失败。"""


class RiskControlError(OrderError):
    """风控触发：滑块、临时封禁、token 失效等。"""


def _jitter():
    time.sleep(random.uniform(*STEP_JITTER))


def step1_submit_order_request(
    session,
    secret_str: str,
    train_date: str,
    from_name: str,
    to_name: str,
    timeout: int = 10,
) -> None:
    """第1步：提交预占请求。"""
    url = f"{BASE_URL}/otn/leftTicket/submitOrderRequest"
    data = {
        "secretStr": urllib.parse.unquote(secret_str),
        "train_date": train_date,
        "back_train_date": train_date,
        "tour_flag": "dc",
        "purpose_codes": "ADULT",
        "query_from_station_name": from_name,
        "query_to_station_name": to_name,
        "undefined": "",
    }
    r = session.post(url, data=data, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    if body.get("status") is not True:
        msgs = body.get("messages") or body.get("data") or "未知错误"
        raise OrderError(f"submitOrderRequest 失败: {msgs}")


def step2_init_dc(session, timeout: int = 15) -> dict:
    """第2步：拉确认页 HTML 并提取 token / leftTicketStr / train_no 等。"""
    url = f"{BASE_URL}/otn/confirmPassenger/initDc"
    r = session.post(url, data={"_json_att": ""}, timeout=timeout)
    r.raise_for_status()
    text = r.text

    def _f(pattern: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1) if m else None

    token = _f(r"globalRepeatSubmitToken = '([^']+)'")
    if not token:
        if "网络忙" in text or "系统繁忙" in text or len(text) < 500:
            raise RiskControlError("initDc 返回异常（疑似风控/滑块/未登录）")
        raise OrderError("未提取到 REPEAT_SUBMIT_TOKEN（页面结构可能变更）")

    return {
        "token": token,
        "key_check_isChange": _f(r"'key_check_isChange':'([^']+)'") or "",
        "leftTicketStr": _f(r"'leftTicketStr':'([^']+)'") or "",
        "train_location": _f(r"'train_location':'([^']+)'") or "",
        "station_train_code": _f(r"'station_train_code':'([^']+)'") or "",
        "train_no": _f(r"'train_no':'([^']+)'") or "",
    }


def step3_get_passengers(session, token: str, timeout: int = 10) -> list[dict]:
    """第3步：拉账号下的常用联系人（下单链中使用，需 token）。"""
    url = f"{BASE_URL}/otn/confirmPassenger/getPassengerDTOs"
    r = session.post(
        url,
        data={"_json_att": "", "REPEAT_SUBMIT_TOKEN": token},
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("status") is not True:
        raise OrderError(f"getPassengerDTOs 失败: {body.get('messages')}")
    return body.get("data", {}).get("normal_passengers", []) or []


def fetch_passenger_list(session, timeout: int = 10) -> list[dict]:
    """独立拉取常用联系人（仅需登录态 cookie，不依赖下单流程）。

    用于 UI 在用户未发起下单前预加载乘客多选框。
    """
    url = f"{BASE_URL}/otn/passengers/query"
    r = session.post(
        url,
        data={"pageIndex": "1", "pageSize": "99", "_json_att": ""},
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("status") is not True:
        raise OrderError(f"passengers/query 失败: {body.get('messages')}")
    return body.get("data", {}).get("datas", []) or []


def _build_passenger_strs(passengers: list[dict], seat_code: str) -> tuple[str, str]:
    """构造 passengerTicketStr 与 oldPassengerStr。"""
    pt, op = [], []
    for p in passengers:
        pt.append(
            ",".join(
                [
                    seat_code,
                    "0",
                    p.get("passenger_type", "1"),
                    p["passenger_name"],
                    p.get("passenger_id_type_code", "1"),
                    p["passenger_id_no"],
                    p.get("mobile_no", ""),
                    "N",
                    p.get("allEncStr", ""),
                ]
            )
        )
        op.append(
            ",".join(
                [
                    p["passenger_name"],
                    p.get("passenger_id_type_code", "1"),
                    p["passenger_id_no"],
                    p.get("passenger_type", "1"),
                ]
            )
            + "_"
        )
    return "_".join(pt), "".join(op)


def step4_check_order_info(
    session,
    token: str,
    passenger_str: str,
    old_str: str,
    timeout: int = 10,
) -> None:
    """第4步：校验订单信息（席别/票种/乘客是否匹配）。"""
    url = f"{BASE_URL}/otn/confirmPassenger/checkOrderInfo"
    r = session.post(
        url,
        data={
            "cancel_flag": "2",
            "bed_level_order_num": "000000000000000000000000000000",
            "passengerTicketStr": passenger_str,
            "oldPassengerStr": old_str,
            "tour_flag": "dc",
            "randCode": "",
            "whatsSelect": "1",
            "sessionId": "",
            "sig": "",
            "scene": "nc_login",
            "_json_att": "",
            "REPEAT_SUBMIT_TOKEN": token,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("status") is not True:
        raise OrderError(f"checkOrderInfo 失败: {body.get('messages')}")
    data = body.get("data", {})
    if data.get("submitStatus") is not True:
        raise OrderError(f"checkOrderInfo submitStatus=false: {data.get('errMsg')}")
    if data.get("ifShowPassCode") == "Y":
        raise RiskControlError("checkOrderInfo 要求验证码（已触发风控）")


def step5_get_queue_count(
    session,
    token: str,
    dc_info: dict,
    train_date: str,
    from_code: str,
    to_code: str,
    seat_code: str,
    timeout: int = 10,
) -> str:
    """第5步：查询当前排队人数。"""
    d = _dt.datetime.strptime(train_date, "%Y-%m-%d")
    train_date_str = d.strftime("%a %b %d %Y") + " 00:00:00 GMT+0800 (中国标准时间)"
    url = f"{BASE_URL}/otn/confirmPassenger/getQueueCount"
    r = session.post(
        url,
        data={
            "train_date": train_date_str,
            "train_no": dc_info["train_no"],
            "stationTrainCode": dc_info["station_train_code"],
            "seatType": seat_code,
            "fromStationTelecode": from_code,
            "toStationTelecode": to_code,
            "leftTicket": dc_info["leftTicketStr"],
            "purpose_codes": "00",
            "train_location": dc_info["train_location"],
            "_json_att": "",
            "REPEAT_SUBMIT_TOKEN": token,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("status") is not True:
        raise OrderError(f"getQueueCount 失败: {body.get('messages')}")
    data = body.get("data", {})
    if data.get("op_2") == "true":
        raise OrderError("排队人数已超过余票数（基本买不到）")
    return str(data.get("count", "?"))


def step6_confirm_single_for_queue(
    session,
    token: str,
    dc_info: dict,
    passenger_str: str,
    old_str: str,
    timeout: int = 15,
) -> None:
    """第6步：真正提交订单（旧名 confirmHB）。"""
    url = f"{BASE_URL}/otn/confirmPassenger/confirmSingleForQueue"
    r = session.post(
        url,
        data={
            "passengerTicketStr": passenger_str,
            "oldPassengerStr": old_str,
            "randCode": "",
            "purpose_codes": "00",
            "key_check_isChange": dc_info["key_check_isChange"],
            "leftTicketStr": dc_info["leftTicketStr"],
            "train_location": dc_info["train_location"],
            "choose_seats": "",
            "seatDetailType": "000",
            "whatsSelect": "1",
            "roomType": "00",
            "dwAll": "N",
            "_json_att": "",
            "REPEAT_SUBMIT_TOKEN": token,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("status") is not True:
        raise OrderError(f"confirmSingleForQueue 失败: {body.get('messages')}")
    data = body.get("data", {})
    if data.get("submitStatus") is not True:
        raise OrderError(
            f"confirmSingleForQueue submitStatus=false: {data.get('errMsg')}"
        )


def step7_query_order_wait_time(
    session,
    token: str,
    max_wait: int = 90,
    timeout: int = 10,
) -> str:
    """第7步：轮询排队/出票结果，返回订单号。"""
    url = f"{BASE_URL}/otn/confirmPassenger/queryOrderWaitTime"
    deadline = time.time() + max_wait
    while time.time() < deadline:
        r = session.get(
            url,
            params={
                "random": str(int(time.time() * 1000)),
                "tourFlag": "dc",
                "_json_att": "",
                "REPEAT_SUBMIT_TOKEN": token,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        body = r.json()
        if body.get("status") is not True:
            raise OrderError(f"queryOrderWaitTime 失败: {body.get('messages')}")
        data = body.get("data", {})
        wait_time = data.get("waitTime", -100)
        order_id = data.get("orderId")
        if wait_time == -1 and order_id:
            return str(order_id)
        if wait_time == -2:
            raise OrderError(f"出票失败: {data.get('msg', '订单已取消或排队失败')}")
        if wait_time == -3:
            raise OrderError("订单已撤销")
        time.sleep(2)
    raise OrderError(f"排队超时（{max_wait}s 未出票）")


def run_order_chain(
    session,
    *,
    secret_str: str,
    train_date: str,
    from_name: str,
    to_name: str,
    from_code: str,
    to_code: str,
    seat_name: str,
    passenger_names: list[str],
    dry_run: bool = False,
    on_log: Callable[[str, str], None] = lambda m, t="info": None,
) -> str | None:
    """整条 7 步链。dry_run 时跳过最终 confirm 与排队。返回订单号或 None。"""
    if seat_name not in SEAT_TYPE_CODE:
        raise OrderError(f"不支持的席别: {seat_name}")
    seat_code = SEAT_TYPE_CODE[seat_name]

    on_log(f"[1/7] 提交预占请求 {from_name}→{to_name} {train_date}", "info")
    step1_submit_order_request(session, secret_str, train_date, from_name, to_name)
    _jitter()

    on_log("[2/7] 进入下单页 / 提取 token", "info")
    dc = step2_init_dc(session)
    on_log(
        f"  ✓ token={dc['token'][:8]}... 车次={dc['station_train_code']}",
        "info",
    )
    _jitter()

    on_log("[3/7] 拉取乘客列表", "info")
    all_pax = step3_get_passengers(session, dc["token"])
    selected = [p for p in all_pax if p.get("passenger_name") in passenger_names]
    if not selected:
        avail = [p.get("passenger_name") for p in all_pax]
        raise OrderError(f"账号下没有匹配乘客: {passenger_names}（可用: {avail}）")
    on_log(
        "  ✓ 已选乘客: " + ", ".join(p["passenger_name"] for p in selected),
        "info",
    )
    _jitter()

    pt_str, op_str = _build_passenger_strs(selected, seat_code)

    on_log("[4/7] 校验订单信息", "info")
    step4_check_order_info(session, dc["token"], pt_str, op_str)
    _jitter()

    on_log("[5/7] 查询排队人数", "info")
    cnt = step5_get_queue_count(
        session,
        dc["token"],
        dc,
        train_date,
        from_code,
        to_code,
        seat_code,
    )
    on_log(f"  ✓ 当前排队: {cnt} 人", "info")
    _jitter()

    if dry_run:
        on_log("[6/7] [DRY-RUN] 跳过 confirmSingleForQueue 提交", "info")
        on_log("[7/7] [DRY-RUN] 跳过排队等待", "info")
        on_log("✓ Dry-run 完成：所有前置步骤通过", "ok")
        return None

    on_log("[6/7] 提交订单（confirmSingleForQueue）...", "info")
    step6_confirm_single_for_queue(session, dc["token"], dc, pt_str, op_str)
    _jitter()

    on_log("[7/7] 等待排队 / 出票...", "info")
    order_id = step7_query_order_wait_time(session, dc["token"])
    on_log(
        f"✓✓✓ 出票成功！订单号: {order_id}（请 30 分钟内到 12306 App 支付）",
        "ok",
    )
    return order_id
