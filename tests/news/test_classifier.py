"""뉴스 키워드 분류기 — 부정 키워드, 거시 키워드, 보유 종목 매칭."""
from __future__ import annotations

from prog_stock.news.classifier import (
    MACRO_TOKENS,
    NEGATIVE_TOKENS,
    classify,
    is_holding_relevant,
)
from prog_stock.news.models import NewsItem, Priority


class TestClassifier:
    def test_negative_keyword_triggers_high(self):
        item = NewsItem(headline="ABC전자 대표이사 횡령 혐의 수사 착수", source="naver_rss")
        item = classify(item)
        assert item.priority == Priority.HIGH
        assert "횡령" in item.keywords

    def test_macro_keyword_medium(self):
        item = NewsItem(headline="FOMC 6월 기준금리 동결 시사", source="reuters_rss")
        item = classify(item)
        assert item.priority == Priority.MEDIUM

    def test_neutral_headline_low(self):
        item = NewsItem(headline="ABC전자 신제품 발표 예정", source="naver_rss")
        item = classify(item)
        assert item.priority == Priority.LOW

    def test_multiple_negative_keywords_captured(self):
        item = NewsItem(headline="회계부정 적발로 거래정지 가능성", source="hankyung_rss")
        item = classify(item)
        assert item.priority == Priority.HIGH
        assert len(item.keywords) >= 2

    def test_keywords_json_roundtrip(self):
        item = NewsItem(headline="횡령 혐의", source="x", keywords=["횡령"])
        import json
        assert json.loads(item.keywords_json()) == ["횡령"]


class TestHoldingMatch:
    def test_matching_name_returns_symbol(self):
        item = NewsItem(headline="삼성전자 횡령 의혹", source="x")
        sym = is_holding_relevant(item, {"005930": "삼성전자"})
        assert sym == "005930"

    def test_no_match_returns_none(self):
        item = NewsItem(headline="다른 회사 뉴스", source="x")
        sym = is_holding_relevant(item, {"005930": "삼성전자"})
        assert sym is None

    def test_empty_name_skipped(self):
        item = NewsItem(headline="아무 뉴스", source="x")
        sym = is_holding_relevant(item, {"005930": ""})
        assert sym is None
