"""百度贴吧 HTTP API 封装。"""

import hashlib
import json
import time

import requests

from .config import DEFAULT_CONFIG
from .logger import logger

SIGN_KEY = "tiebaclient!!!"


def get_session(config: dict) -> requests.Session:
    session = requests.Session()
    session.cookies.set("BDUSS", config.get("bduss", ""), domain=".baidu.com")
    session.headers.update(
        {
            "User-Agent": config.get("user_agent", DEFAULT_CONFIG["user_agent"]),
            "Accept": "application/json, text/plain, */*",
        }
    )
    proxy = config.get("proxy", "")
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    return session


def get_tbs(session: requests.Session, timeout: int = 10) -> str | None:
    """获取 tbs 防跨站令牌，同时验证登录状态。"""
    resp = session.get("http://tieba.baidu.com/dc/common/tbs", timeout=timeout)
    data = resp.json()
    if data.get("is_login") == 1:
        return data["tbs"]
    return None


def _client_sign(params: dict) -> str:
    """为客户端 API 请求计算签名。"""
    sign_str = "".join(f"{k}={params[k]}" for k in sorted(params)) + SIGN_KEY
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest()


def get_user_info(session: requests.Session, timeout: int = 10) -> dict | None:
    """获取当前登录的用户信息（纯 HTTP，无重定向）。

    返回 {"name": 用户名, "nickname": 昵称} 或 None。
    """
    url = "http://tieba.baidu.com/i/sys/user_json"
    resp = session.get(url, timeout=timeout)
    data = json.loads(resp.content.decode("utf-8", errors="ignore"))
    name = data.get("raw_name", "")
    if not name:
        return None
    creator = data.get("creator", {})
    return {
        "name": name,
        "nickname": creator.get("show_nickname", "") or creator.get("name_show", ""),
    }


def get_followed_tiebas(session: requests.Session, timeout: int = 30) -> list[dict]:
    """通过客户端 API 获取所有关注的贴吧列表（含签到状态）。"""
    url = "http://c.tieba.baidu.com/c/f/forum/like"
    bduss = session.cookies.get("BDUSS", domain=".baidu.com") or ""

    tiebas = []
    page = 1
    while True:
        params = {
            "BDUSS": bduss,
            "_client_version": "8.8.8.6",
            "page_no": str(page),
            "page_size": "200",
        }
        params["sign"] = _client_sign(params)

        resp = requests.post(url, data=params, timeout=timeout)
        result = resp.json()
        if result.get("error_code") != "0":
            break

        forum_list = result.get("forum_list", {})
        forums = forum_list.get("non-gconforum", []) + forum_list.get("gconforum", [])
        if not forums:
            break

        for forum in forums:
            tiebas.append(
                {
                    "name": forum.get("name"),
                    "id": forum.get("id"),
                    "is_sign": str(forum.get("is_sign")) == "1",
                }
            )

        if not result.get("has_more", "0") == "1":
            break
        page += 1

    return tiebas


def sign_via_client(
    session: requests.Session, tbs: str, kw: str, timeout: int = 10
) -> tuple[bool, str]:
    """通过客户端接口签到（成功率更高）。"""
    url = "http://c.tieba.baidu.com/c/c/forum/sign"
    bduss = session.cookies.get("BDUSS", domain=".baidu.com") or ""
    params = {
        "BDUSS": bduss,
        "fid": "",
        "kw": kw,
        "tbs": tbs,
    }
    params["sign"] = _client_sign(params)

    resp = requests.post(url, data=params, timeout=timeout)
    result = resp.json()
    code = result.get("error_code", "-1")
    if code == "0":
        info = result.get("user_info", {})
        rank = info.get("sign_time", "?")
        cont = info.get("cont_sign_num", "?")
        return True, f"签到成功 (第{rank}个, 连签{cont}天)"
    if code == "160002":
        return True, "今日已签到"
    return False, result.get("error_msg", f"错误码 {code}")


def sign_via_web(
    session: requests.Session, tbs: str, kw: str, timeout: int = 10
) -> tuple[bool, str]:
    """通过 Web 接口签到（备用方案）。"""
    url = "http://tieba.baidu.com/sign/add"
    headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
    data = {"ie": "utf-8", "kw": kw, "tbs": tbs}

    resp = session.post(url, headers=headers, data=data, timeout=timeout)
    result = resp.json()
    no = result.get("no")
    if no == 0:
        return True, "签到成功"
    if no == 1101:
        return True, "今日已签到"
    return False, result.get("error", f"错误码 {no}")


def sign_one(
    session: requests.Session,
    tbs: str,
    kw: str,
    timeout: int = 10,
    max_retries: int = 3,
) -> tuple[bool, str]:
    """尝试签到单个贴吧，支持重试。优先客户端接口，失败回退 Web 接口。

    每一次尝试的细节都写入文件日志（logger.info），界面只看到最终结果。"""
    last_err = ""
    for attempt in range(1, max_retries + 1):
        logger.info(f"  └ {kw}吧 第{attempt}次尝试 - 客户端接口")
        try:
            ok, msg = sign_via_client(session, tbs, kw, timeout)
            if ok:
                logger.info(f"  └ {kw}吧 客户端接口成功: {msg}")
                return ok, msg
            last_err = msg
            logger.info(f"  └ {kw}吧 客户端接口失败: {msg}")
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            logger.info(f"  └ {kw}吧 客户端接口异常: {last_err}")

        logger.info(f"  └ {kw}吧 第{attempt}次尝试 - Web 接口（回退）")
        try:
            ok, msg = sign_via_web(session, tbs, kw, timeout)
            if ok:
                logger.info(f"  └ {kw}吧 Web 接口成功: {msg}")
                return ok, msg
            last_err = msg
            logger.info(f"  └ {kw}吧 Web 接口失败: {msg}")
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            logger.info(f"  └ {kw}吧 Web 接口异常: {last_err}")
        if attempt < max_retries:
            time.sleep(1)
    logger.info(f"  └ {kw}吧 共重试 {max_retries} 次，全部失败: {last_err}")
    return False, last_err


def sign_all_one_key(
    session: requests.Session, tbs: str, timeout: int = 30
) -> tuple[bool, str, dict]:
    """百度贴吧一键签到，返回 (成功, 消息, 详情)。"""
    url = "http://tieba.baidu.com/tbmall/onekeySignin1"
    data = {"ie": "utf-8", "tbs": tbs}
    resp = session.post(url, data=data, timeout=timeout)
    result = resp.json()
    no = result.get("no")
    detail = result.get("data", {})

    signed = detail.get("signedForumAmount", 0)
    failed = detail.get("signedForumAmountFail", 0)
    unsigned = detail.get("unsignedForumAmount", 0)

    if no == 0:
        return True, f"一键签到完成: 成功 {signed} 个, 新签到 {unsigned} 个", detail
    if no == 2280006:
        return True, f"所有贴吧今日均已签到 (共 {signed} 个)", detail
    if no == 2150040:
        return False, "一键签到需要贴吧会员权限，请使用「逐个签到」", detail
    if no == 2280007:
        msg = f"部分签到完成: 成功 {signed} 个, 失败 {failed} 个, 剩余 {unsigned} 个"
        return False, msg, detail

    error = result.get("error", "未知错误")
    return False, f"{error} (错误码 {no})", detail


def _format_user(uinfo: dict | None) -> str:
    """将 get_user_info 返回的 dict 格式化为显示字符串。"""
    if not uinfo:
        return "未知用户"
    name = uinfo.get("name", "")
    nickname = uinfo.get("nickname", "")
    if name and nickname and name != nickname:
        return f"{nickname} ({name})"
    return name or nickname or "未知用户"
