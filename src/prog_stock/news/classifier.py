"""키워드 기반 우선순위 분류기.

LLM 감성분석은 위험(맥락 무시·환각·언론 의도) → 단순 키워드 매칭으로 시작.
부정 키워드 매칭이면 priority=HIGH로 알림 트리거.
"""
from __future__ import annotations

import re

from prog_stock.news.models import NewsItem, Priority


NEGATIVE_TOKENS = (
    # 회사 거버넌스 / 회계
    "횡령", "배임", "분식", "분식회계", "회계부정", "수사", "기소", "압수수색",
    "대표이사 사임", "대표 사임", "대표이사 사임", "대표이사 교체", "이사회 갈등",
    # 거래 관련
    "거래정지", "상장폐지", "관리종목 지정", "투자위험", "투자경고", "단기과열",
    # 사업 관련
    "감자", "유상증자", "전환사채", "신주발행", "리콜", "대규모 손실", "어닝쇼크",
    "실적 부진", "매출 감소", "영업적자", "적자 전환", "구조조정", "정리해고",
    # 외부
    "제재", "벌금", "과징금", "패소", "패소 판결",
)

POSITIVE_TOKENS = (
    "어닝서프라이즈", "최대 실적", "신고가", "대규모 수주", "신제품 출시",
    "흑자 전환", "실적 호조", "이익 급증",
)

MACRO_TOKENS = (
    "fomc", "fed", "연준", "금통위", "기준금리", "통화정책", "양적완화", "긴축",
    "cpi", "pce", "물가", "고용지표", "비농업", "옵션만기",
)


def _normalize(text: str) -> str:
    return text.lower().strip()


def classify(item: NewsItem) -> NewsItem:
    """헤드라인을 분석해 우선순위와 매칭 키워드를 채워 반환."""
    text = _normalize(item.headline)
    matches: list[str] = []

    for tok in NEGATIVE_TOKENS:
        if tok.lower() in text:
            matches.append(tok)

    macro_match = [tok for tok in MACRO_TOKENS if tok in text]
    has_positive = any(tok.lower() in text for tok in POSITIVE_TOKENS)

    if matches:
        item.priority = Priority.HIGH
        item.keywords = matches
    elif macro_match:
        item.priority = Priority.MEDIUM
        item.keywords = macro_match
    elif has_positive:
        item.priority = Priority.LOW
        item.keywords = [tok for tok in POSITIVE_TOKENS if tok.lower() in text]
    else:
        item.priority = Priority.LOW

    return item


def is_holding_relevant(item: NewsItem, symbols_to_names: dict[str, str]) -> str | None:
    """헤드라인에 보유 종목 이름이 들어 있으면 symbol 반환."""
    text = item.headline
    for symbol, name in symbols_to_names.items():
        if not name:
            continue
        if name in text:
            return symbol
    return None
