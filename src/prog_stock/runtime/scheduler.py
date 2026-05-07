"""APScheduler 래퍼 — 장 시작/마감/주기 작업."""
from __future__ import annotations

from datetime import time
from typing import Callable

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = structlog.get_logger(__name__)


class TradingScheduler:
    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler(timezone="Asia/Seoul")

    def daily_at(self, name: str, hhmm: time, fn: Callable[[], None]) -> None:
        trigger = CronTrigger(hour=hhmm.hour, minute=hhmm.minute, day_of_week="mon-fri")
        self.scheduler.add_job(fn, trigger, id=name, replace_existing=True)
        log.info("schedule_added", name=name, time=hhmm.isoformat())

    def every_minutes(self, name: str, minutes: int, fn: Callable[[], None]) -> None:
        trigger = CronTrigger(minute=f"*/{minutes}", hour="9-15", day_of_week="mon-fri")
        self.scheduler.add_job(fn, trigger, id=name, replace_existing=True)

    def start(self) -> None:
        self.scheduler.start()
        log.info("scheduler_started")

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)
        log.info("scheduler_stopped")
