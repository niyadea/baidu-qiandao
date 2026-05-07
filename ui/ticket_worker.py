"""抢票后台 worker（仅查询/轮询，不下单）。"""

import json
import threading
from datetime import datetime
from typing import Callable

from core import damai, ticket12306, ticket12306_order


class _BaseWorker:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.on_log: Callable[[str, str], None] = lambda msg, tag="info": None
        self.on_status: Callable[[str], None] = lambda text: None
        self.on_finish: Callable[[], None] = lambda: None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, *args, **kwargs) -> bool:
        if self.is_running():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._safe_run, args=args, kwargs=kwargs, daemon=True
        )
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    def _safe_run(self, *args, **kwargs):
        try:
            self._run(*args, **kwargs)
        except Exception as e:
            self.on_log(f"[异常] {type(e).__name__}: {e}", "fail")
        finally:
            self.on_finish()

    def _run(self, *args, **kwargs):
        raise NotImplementedError

    def _wait_until_clock(self, when_str: str) -> bool:
        try:
            h, m, s = (int(x) for x in when_str.split(":"))
        except (ValueError, IndexError):
            self.on_log(f"定时格式无效（应为 HH:MM:SS）: {when_str}", "fail")
            return False
        now = datetime.now()
        target = now.replace(hour=h, minute=m, second=s, microsecond=0)
        if target <= now:
            self.on_log("定时点已过，立即开始", "info")
            return True
        delta = (target - now).total_seconds()
        self.on_log(f"等待至 {target.strftime('%H:%M:%S')}（{int(delta)}s 后）", "info")
        if self._stop.wait(delta):
            return False
        return True


# ── 12306 ───────────────────────────────────────────────


def _match_train_type(code: str, types: list[str]) -> bool:
    if not types:
        return True
    head = code[0] if code else "X"
    if head in ("G", "C") and "G/C" in types:
        return True
    if head in ("D", "Z", "T", "K") and head in types:
        return True
    if head not in ("G", "C", "D", "Z", "T", "K") and "其他" in types:
        return True
    return False


class Ticket12306Worker(_BaseWorker):
    def _run(
        self,
        cookie: str,
        from_name: str,
        to_name: str,
        date: str,
        types: list[str],
        seat: str,
        when_mode: str,
        when_str: str,
        interval: int,
        auto_order: bool = False,
        dry_run: bool = True,
        passenger_names: list[str] | None = None,
    ):
        interval = max(1, int(interval))  # 硬下限 1s

        if when_mode == "timed" and not self._wait_until_clock(when_str):
            return

        try:
            stations = ticket12306.get_station_dict()
        except Exception as e:
            self.on_log(f"加载站点字典失败: {e}", "fail")
            return
        from_code = stations.get(from_name)
        to_code = stations.get(to_name)
        if not from_code or not to_code:
            self.on_log(
                f"未识别的站点: {from_name!r} / {to_name!r}（请填准确的中文站名）",
                "fail",
            )
            return
        self.on_log(
            f"站点解析: {from_name}({from_code}) → {to_name}({to_code})", "info"
        )
        if auto_order:
            mode = "DRY-RUN" if dry_run else "REAL"
            self.on_log(
                f"⚠ 自动下单已开启（{mode}），命中后将自动走 7 步下单链；"
                f"乘客={passenger_names or []}",
                "info",
            )

        session = ticket12306.make_session(cookie)
        idx = 0
        while not self._stop.is_set():
            idx += 1
            self.on_status(f"第 {idx} 次查询")
            try:
                trains = ticket12306.query_left_tickets(
                    session, from_code, to_code, date
                )
            except Exception as e:
                self.on_log(f"[查询失败] {type(e).__name__}: {e}", "fail")
                if self._stop.wait(interval):
                    return
                continue

            hits = [
                t
                for t in trains
                if t["can_buy"]
                and _match_train_type(t["code"], types)
                and t["seats"].get(seat, "")
                and t["seats"].get(seat) not in ("无", "-", "0")
            ]
            if hits:
                self.on_log(f"✓ 命中 {len(hits)} 趟车有 {seat} 余票！", "ok")
                for h in hits:
                    self.on_log(
                        f"  {h['code']} {h['start_time']}→{h['arrive_time']} "
                        f"{seat}: {h['seats'][seat]}",
                        "ok",
                    )
                if auto_order:
                    if not passenger_names:
                        self.on_log(
                            "⚠ 自动下单开启但未指定乘客，已停止下单流程", "fail"
                        )
                        return
                    self._try_order(
                        session,
                        hits[0],
                        date,
                        from_name,
                        to_name,
                        from_code,
                        to_code,
                        seat,
                        passenger_names,
                        dry_run,
                    )
                    return  # 下单流程跑完就停（无论成败）
            else:
                self.on_log(f"  第 {idx} 轮：{len(trains)} 趟车无 {seat} 余票", "info")
            if self._stop.wait(interval):
                return

    def _try_order(
        self,
        session,
        hit,
        date,
        from_name,
        to_name,
        from_code,
        to_code,
        seat,
        passenger_names,
        dry_run,
    ):
        self.on_status("下单中...")
        self.on_log(f"────── 进入下单流程（车次 {hit['code']}）──────", "info")
        try:
            ticket12306_order.run_order_chain(
                session,
                secret_str=hit["secret"],
                train_date=date,
                from_name=from_name,
                to_name=to_name,
                from_code=from_code,
                to_code=to_code,
                seat_name=seat,
                passenger_names=passenger_names,
                dry_run=dry_run,
                on_log=self.on_log,
            )
        except ticket12306_order.RiskControlError as e:
            self.on_log(
                f"⚠ 触发风控/滑块，已停止：{e}（请到浏览器手动下单或稍后再试）",
                "fail",
            )
        except ticket12306_order.OrderError as e:
            self.on_log(f"[下单失败] {e}", "fail")
        except Exception as e:
            self.on_log(f"[下单异常] {type(e).__name__}: {e}", "fail")


# ── 大麦 ────────────────────────────────────────────────


class DamaiWorker(_BaseWorker):
    def _run(
        self,
        cookie: str,
        url_or_id: str,
        when_mode: str,
        when_str: str,
        interval: int,
    ):
        try:
            item_id = damai.extract_item_id(url_or_id)
        except ValueError as e:
            self.on_log(str(e), "fail")
            return
        self.on_log(f"演出 itemId: {item_id}", "info")

        if when_mode == "timed" and not self._wait_until_clock(when_str):
            return

        session = damai.make_session(cookie)
        idx = 0
        last_summary = ""
        while not self._stop.is_set():
            idx += 1
            self.on_status(f"第 {idx} 次查询")
            try:
                detail = damai.fetch_item_detail(session, item_id)
            except Exception as e:
                self.on_log(f"[查询失败] {type(e).__name__}: {e}", "fail")
                if self._stop.wait(interval):
                    return
                continue

            item = detail.get("item", {}) or {}
            title = item.get("itemName") or item.get("title") or "(未知)"
            summary = f"演出: {title}"
            if summary != last_summary:
                self.on_log(summary, "info")
                last_summary = summary

            blob = json.dumps(detail, ensure_ascii=False)
            if '"hasStock":true' in blob or '"soldOut":false' in blob:
                self.on_log("✓ 检测到票档库存！请到浏览器手动下单", "ok")
            else:
                self.on_log(f"  第 {idx} 轮：暂无可用库存", "info")
            if self._stop.wait(interval):
                return
