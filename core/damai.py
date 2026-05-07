"""大麦网 演出/票档查询 + Cookie 校验。

仅做"下单之前"的查询与轮询，不会自动下单。
"""

import hashlib
import json
import re
import time

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.damai.cn",
}

MTOP_HOST = "https://mtop.damai.cn/h5"
APP_KEY = "12574478"
DETAIL_API = "mtop.alibaba.damai.detail.getdetail"
DETAIL_VERSION = "1.2"


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
        s.cookies.set(k, v, domain=".damai.cn")
    return s


def extract_item_id(url_or_id: str) -> str:
    """从 URL 或纯数字中提取 itemId。"""
    s = url_or_id.strip()
    if s.isdigit():
        return s
    m = re.search(r"[?&]id=(\d+)", s)
    if m:
        return m.group(1)
    m = re.search(r"/item/(\d+)", s)
    if m:
        return m.group(1)
    raise ValueError(f"无法从中提取 itemId: {url_or_id!r}")


def _h5_tk_token(session: requests.Session) -> str | None:
    val = session.cookies.get("_m_h5_tk")
    if not val:
        return None
    return val.split("_", 1)[0]


def _mtop_sign(token: str, t: str, data_str: str) -> str:
    s = f"{token}&{t}&{APP_KEY}&{data_str}"
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def mtop_call(
    session: requests.Session,
    api: str,
    version: str,
    data: dict,
    timeout: int = 10,
) -> dict:
    """调用 mtop 接口（GET，自动签名）。"""
    token = _h5_tk_token(session)
    if not token:
        raise RuntimeError("缺少 _m_h5_tk cookie，无法签名 mtop 请求")
    t = str(int(time.time() * 1000))
    data_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    sign = _mtop_sign(token, t, data_str)
    url = f"{MTOP_HOST}/{api}/{version}/"
    params = {
        "jsv": "2.7.2",
        "appKey": APP_KEY,
        "t": t,
        "sign": sign,
        "api": api,
        "v": version,
        "type": "originaljson",
        "dataType": "json",
        "timeout": "20000",
        "data": data_str,
    }
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def validate_cookie(
    session: requests.Session, timeout: int = 10
) -> tuple[bool, str]:
    """静态校验关键 cookie 是否存在。"""
    missing = []
    if not session.cookies.get("_m_h5_tk"):
        missing.append("_m_h5_tk（mtop 签名 token）")
    if not session.cookies.get("cookie2"):
        missing.append("cookie2（淘系登录态）")
    unb = session.cookies.get("unb")
    if not unb:
        missing.append("unb（淘宝用户 ID，登录后才会有）")
    if missing:
        return False, "Cookie 缺少: " + ", ".join(missing)
    return True, f"Cookie 有效（淘宝用户 ID: {unb}）"


def fetch_item_detail(
    session: requests.Session, item_id: str, timeout: int = 10
) -> dict:
    """拉取演出详情（含场次、票档、库存）。"""
    raw = mtop_call(
        session, DETAIL_API, DETAIL_VERSION, {"itemId": item_id}, timeout
    )
    ret = raw.get("ret") or []
    if not ret or not str(ret[0]).startswith("SUCCESS"):
        raise RuntimeError(f"mtop 返回失败: {ret}")
    return raw.get("data", {})
