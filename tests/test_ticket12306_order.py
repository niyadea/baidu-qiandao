"""12306 自动下单链与相关 worker 的 pytest 单元测试。

不发起真实网络请求；以 _FakeSession 模拟 12306 端点响应。
"""

import inspect
import json

import pytest

from core import ticket12306_order as order
from ui.ticket_worker import Ticket12306Worker

# ── 测试夹具 ──────────────────────────────────────────────


class _Resp:
    def __init__(self, body=None, text=None):
        self._body = body
        self.text = text if text is not None else json.dumps(body)

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


_INIT_DC_HTML = (
    "<html>"
    "var globalRepeatSubmitToken = 'TOK_FAKE_12345678'; "
    "var ticketInfoForPassengerForm={"
    "'key_check_isChange':'KEY_FAKE',"
    "'leftTicketStr':'LEFT_FAKE',"
    "'train_location':'P3',"
    "'station_train_code':'G123',"
    "'train_no':'24000000G1234'"
    "};</html>"
)


class _FakeSession:
    """记录所有调用的 url 与 data；按 endpoint 路由返回伪响应。"""

    def __init__(self, allow_confirm: bool = False, allow_query_wait: bool = False):
        self.calls: list[tuple[str, str]] = []
        self._allow_confirm = allow_confirm
        self._allow_query_wait = allow_query_wait
        self._wait_calls = 0

    def post(self, url, data=None, timeout=10, **kw):
        self.calls.append(("POST", url))
        if "submitOrderRequest" in url:
            return _Resp({"status": True})
        if "initDc" in url:
            return _Resp(body=None, text=_INIT_DC_HTML)
        if "passengers/query" in url:
            return _Resp(
                {
                    "status": True,
                    "data": {
                        "datas": [
                            {
                                "passenger_name": "张三",
                                "passenger_id_no": "110101199001011234",
                            },
                        ]
                    },
                }
            )
        if "getPassengerDTOs" in url:
            return _Resp(
                {
                    "status": True,
                    "data": {
                        "normal_passengers": [
                            {
                                "passenger_name": "张三",
                                "passenger_id_no": "110101199001011234",
                                "passenger_id_type_code": "1",
                                "passenger_type": "1",
                                "mobile_no": "13800138000",
                                "allEncStr": "ENC_FAKE",
                            }
                        ]
                    },
                }
            )
        if "checkOrderInfo" in url:
            return _Resp(
                {"status": True, "data": {"submitStatus": True, "ifShowPassCode": "N"}}
            )
        if "getQueueCount" in url:
            return _Resp({"status": True, "data": {"count": "0", "op_2": "false"}})
        if "confirmSingleForQueue" in url:
            if not self._allow_confirm:
                raise AssertionError("dry_run 不应调用 confirmSingleForQueue")
            return _Resp({"status": True, "data": {"submitStatus": True}})
        return _Resp({"status": True})

    def get(self, url, params=None, timeout=10, **kw):
        self.calls.append(("GET", url))
        if "queryOrderWaitTime" in url:
            if not self._allow_query_wait:
                raise AssertionError("dry_run 不应调用 queryOrderWaitTime")
            self._wait_calls += 1
            return _Resp(
                {
                    "status": True,
                    "data": {
                        "waitTime": -1,
                        "orderId": "EB12345678",
                    },
                }
            )
        return _Resp({"status": True})


@pytest.fixture(autouse=True)
def _no_jitter(monkeypatch):
    """关闭随机 sleep，让测试瞬时跑完。"""
    monkeypatch.setattr(order, "STEP_JITTER", (0.0, 0.0))


# ── 单元测试 ──────────────────────────────────────────────


def test_seat_type_code_has_common_seats():
    assert order.SEAT_TYPE_CODE["二等座"] == "O"
    assert order.SEAT_TYPE_CODE["一等座"] == "M"
    assert order.SEAT_TYPE_CODE["商务座"] == "9"
    assert "硬卧" in order.SEAT_TYPE_CODE


def test_step1_submit_order_request_success():
    sess = _FakeSession()
    order.step1_submit_order_request(sess, "SEC", "2026-06-01", "上海", "北京")
    assert any("submitOrderRequest" in u for _, u in sess.calls)


def test_step1_submit_order_request_failure_raises():
    class _Sess(_FakeSession):
        def post(self, url, data=None, timeout=10, **kw):
            return _Resp({"status": False, "messages": ["车次已停售"]})

    with pytest.raises(order.OrderError, match="submitOrderRequest"):
        order.step1_submit_order_request(_Sess(), "S", "2026-06-01", "A", "B")


def test_step2_init_dc_extracts_token_and_fields():
    dc = order.step2_init_dc(_FakeSession())
    assert dc["token"] == "TOK_FAKE_12345678"
    assert dc["leftTicketStr"] == "LEFT_FAKE"
    assert dc["station_train_code"] == "G123"
    assert dc["train_no"] == "24000000G1234"


def test_step2_init_dc_short_response_triggers_risk():
    class _Sess:
        def post(self, url, data=None, timeout=10, **kw):
            return _Resp(body=None, text="网络忙，请稍后再试")

    with pytest.raises(order.RiskControlError):
        order.step2_init_dc(_Sess())


def test_fetch_passenger_list_returns_datas():
    pax = order.fetch_passenger_list(_FakeSession())
    assert isinstance(pax, list) and pax
    assert pax[0]["passenger_name"] == "张三"


def test_fetch_passenger_list_failure_raises():
    class _Sess:
        def post(self, url, data=None, timeout=10, **kw):
            return _Resp({"status": False, "messages": ["未登录"]})

    with pytest.raises(order.OrderError, match="passengers/query"):
        order.fetch_passenger_list(_Sess())


def test_build_passenger_strs_format():
    pax = [
        {
            "passenger_name": "张三",
            "passenger_id_no": "110101199001011234",
            "passenger_id_type_code": "1",
            "passenger_type": "1",
            "mobile_no": "13800138000",
            "allEncStr": "ENC",
        }
    ]
    pt, op = order._build_passenger_strs(pax, seat_code="O")
    # passengerTicketStr: seat,0,ptype,name,idtype,id,phone,N,enc
    parts = pt.split(",")
    assert parts[0] == "O"
    assert parts[1] == "0"
    assert parts[3] == "张三"
    assert parts[5] == "110101199001011234"
    assert parts[7] == "N"
    # oldPassengerStr: name,idtype,id,ptype_
    assert op == "张三,1,110101199001011234,1_"


def test_run_order_chain_dry_run_skips_confirm_and_query():
    sess = _FakeSession(allow_confirm=False, allow_query_wait=False)
    logs: list[tuple[str, str]] = []
    result = order.run_order_chain(
        sess,
        secret_str="SEC",
        train_date="2026-06-01",
        from_name="上海",
        to_name="北京",
        from_code="SHH",
        to_code="BJP",
        seat_name="二等座",
        passenger_names=["张三"],
        dry_run=True,
        on_log=lambda m, t="info": logs.append((t, m)),
    )
    assert result is None
    urls = [u for _, u in sess.calls]
    assert not any("confirmSingleForQueue" in u for u in urls)
    assert not any("queryOrderWaitTime" in u for u in urls)
    assert any("DRY-RUN" in m for _, m in logs)


def test_run_order_chain_real_calls_confirm_and_returns_order_id():
    sess = _FakeSession(allow_confirm=True, allow_query_wait=True)
    order_id = order.run_order_chain(
        sess,
        secret_str="SEC",
        train_date="2026-06-01",
        from_name="上海",
        to_name="北京",
        from_code="SHH",
        to_code="BJP",
        seat_name="二等座",
        passenger_names=["张三"],
        dry_run=False,
    )
    assert order_id == "EB12345678"
    urls = [u for _, u in sess.calls]
    assert any("confirmSingleForQueue" in u for u in urls)
    assert any("queryOrderWaitTime" in u for u in urls)


def test_run_order_chain_unknown_passenger_raises():
    sess = _FakeSession()
    with pytest.raises(order.OrderError, match="没有匹配乘客"):
        order.run_order_chain(
            sess,
            secret_str="S",
            train_date="2026-06-01",
            from_name="A",
            to_name="B",
            from_code="A",
            to_code="B",
            seat_name="二等座",
            passenger_names=["不存在的人"],
            dry_run=True,
        )


def test_run_order_chain_unknown_seat_raises():
    with pytest.raises(order.OrderError, match="不支持的席别"):
        order.run_order_chain(
            _FakeSession(),
            secret_str="S",
            train_date="2026-06-01",
            from_name="A",
            to_name="B",
            from_code="A",
            to_code="B",
            seat_name="贵宾舱",
            passenger_names=["张三"],
            dry_run=True,
        )


def test_worker_run_has_1s_lower_bound():
    """Ticket12306Worker._run 必须包含 1s 硬下限，防止 UI 误传 0。"""
    src = inspect.getsource(Ticket12306Worker._run)
    assert "max(1, int(interval))" in src
