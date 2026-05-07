"""12306 余票查询 / Cookie 校验 / 站点字典。

仅做"下单之前"的查询与轮询，不会自动下单。
"""

import json
import re
import urllib.parse

import requests

from .logger import logger
from .paths import _base_dir

BASE_URL = "https://kyfw.12306.cn"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://kyfw.12306.cn/otn/leftTicket/init",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

SEAT_INDEX = {
    "商务座": 32,
    "特等座": 25,
    "一等座": 31,
    "二等座": 30,
    "高级软卧": 21,
    "软卧": 23,
    "动卧": 33,
    "硬卧": 28,
    "软座": 24,
    "硬座": 29,
    "无座": 26,
    "其他": 22,
}

STATIONS_CACHE = _base_dir() / "12306_stations.json"
STATIONS_URL = f"{BASE_URL}/otn/resources/js/framework/station_name.js"


def parse_cookie_string(cookie: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in cookie.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def make_session(cookie: str = "") -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    for k, v in parse_cookie_string(cookie).items():
        s.cookies.set(k, v, domain=".12306.cn")
    return s


def validate_cookie(
    session: requests.Session, timeout: int = 10
) -> tuple[bool, str]:
    """通过 /otn/login/checkUser 判定 cookie 是否登录态。"""
    url = f"{BASE_URL}/otn/login/checkUser"
    try:
        r = session.post(url, data={"_json_att": ""}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return False, f"网络错误: {type(e).__name__}: {e}"
    except ValueError:
        return False, f"返回不是 JSON: {r.text[:80]}"

    if data.get("data", {}).get("flag") is True:
        return True, "Cookie 有效（已登录 12306）"
    msgs = data.get("messages") or "未登录或 cookie 已过期"
    return False, f"Cookie 无效: {msgs}"


def get_station_dict(
    session: requests.Session | None = None,
    force_refresh: bool = False,
    timeout: int = 10,
) -> dict[str, str]:
    """返回 {站名: 电报码}（如「北京北」→「VAP」）。带本地 JSON 缓存。"""
    if not force_refresh and STATIONS_CACHE.is_file():
        try:
            cached = json.loads(STATIONS_CACHE.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached:
                return cached
        except (json.JSONDecodeError, OSError):
            pass

    sess = session or make_session()
    r = sess.get(STATIONS_URL, timeout=timeout)
    r.raise_for_status()
    m = re.search(r"='([^']+)'", r.text)
    if not m:
        raise RuntimeError("无法解析 12306 站点 JS（结构变更？）")

    out: dict[str, str] = {}
    for chunk in m.group(1).split("@"):
        parts = chunk.split("|")
        if len(parts) >= 3 and parts[1] and parts[2]:
            out[parts[1]] = parts[2]

    try:
        STATIONS_CACHE.write_text(
            json.dumps(out, ensure_ascii=False), encoding="utf-8"
        )
        logger.info(f"12306 站点字典已刷新: {len(out)} 条 → {STATIONS_CACHE.name}")
    except OSError as e:
        logger.warning(f"12306 站点字典写缓存失败: {e}")
    return out


def query_left_tickets(
    session: requests.Session,
    from_code: str,
    to_code: str,
    train_date: str,
    timeout: int = 10,
) -> list[dict]:
    """leftTicket/queryX 余票查询。返回每趟车的字典（车次、时间、各席别余票）。"""
    session.cookies.set(
        "_jc_save_fromStation",
        urllib.parse.quote(from_code), domain=".12306.cn",
    )
    session.cookies.set(
        "_jc_save_toStation",
        urllib.parse.quote(to_code), domain=".12306.cn",
    )
    session.cookies.set("_jc_save_fromDate", train_date, domain=".12306.cn")

    url = f"{BASE_URL}/otn/leftTicket/queryX"
    params = {
        "leftTicketDTO.train_date": train_date,
        "leftTicketDTO.from_station": from_code,
        "leftTicketDTO.to_station": to_code,
        "purpose_codes": "ADULT",
    }
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if data.get("status") is not True:
        raise RuntimeError(f"queryX 返回失败: {data}")

    out: list[dict] = []
    for raw in data.get("data", {}).get("result", []):
        f = raw.split("|")
        if len(f) < 35:
            continue
        out.append({
            "secret": f[0],
            "train_no": f[2],
            "code": f[3],
            "start_time": f[8],
            "arrive_time": f[9],
            "duration": f[10],
            "can_buy": f[11] == "Y",
            "seats": {n: f[i] for n, i in SEAT_INDEX.items() if f[i]},
        })
    return out
