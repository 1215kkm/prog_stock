"""텔레그램 봇 — 알림 + Kill Switch.

명령:
  /status     현재 잔고, 보유 포지션, 일일 P&L
  /positions  보유 종목 상세
  /today      오늘 매매 후보 + 예정 주문
  /halt       신규 매수 잠금 (보유는 유지)
  /resume     halt 해제
  /stop       전 포지션 시장가 청산 + 시스템 정지 (수동 승인 필요)
"""
from __future__ import annotations

from typing import Callable

import structlog

log = structlog.get_logger(__name__)


class TelegramNotifier:
    """단방향 알림. 양방향 명령 처리는 ControlBot에서."""

    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id

    def send(self, text: str, html: bool = False) -> None:
        if not self.token or not self.chat_id:
            log.info("telegram_skip", text=text[:120])
            return
        import httpx

        try:
            httpx.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML" if html else None,
                    "disable_web_page_preview": True,
                },
                timeout=10.0,
            )
        except Exception as e:
            log.warning("telegram_send_failed", error=str(e))


class ControlBot:
    """양방향 명령 봇.

    handlers는 호출 가능 객체로 외부 주입.
    별도 프로세스/스레드에서 폴링.
    """

    def __init__(
        self,
        token: str,
        chat_id: str,
        handlers: dict[str, Callable[[], str]],
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.handlers = handlers

    def run(self) -> None:
        from telegram.ext import Application, CommandHandler

        app = Application.builder().token(self.token).build()
        for cmd, fn in self.handlers.items():
            async def _handler(update, context, _fn=fn):  # type: ignore[no-untyped-def]
                if str(update.effective_chat.id) != self.chat_id:
                    return  # 화이트리스트
                reply = _fn()
                await update.message.reply_text(reply)
            app.add_handler(CommandHandler(cmd, _handler))
        app.run_polling()
