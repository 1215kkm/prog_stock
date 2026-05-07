# prog_stock — 한국 주식 자동매매

> **성장하는 회사를 추세에 따라 매수하고, 꺾이면 무조건 손절한다.**

윌리엄 오닐(CAN SLIM) + 마크 미너비니(SEPA) 프레임워크를 한국 시장에 적용한 자동매매 시스템.
모의투자에서 검증 후 실거래 자동 게이트.

---

## 빠른 시작

```bash
# 의존성 설치 (uv 사용)
uv sync --extra dev

# 또는 pip
pip install -e ".[dev]"

# 환경변수 설정
cp .env.example .env
# .env 편집 (KIS app key, DART API key, 텔레그램 토큰)

# 모의투자 잔고 PoC
python -m prog_stock.poc.balance

# 인프라 dry-run
python -m prog_stock.runtime.loop --mode dry_run

# 백테스트
python -m prog_stock.backtest.runner --strategy canslim_sepa --years 5

# 페이퍼 트레이딩
python -m prog_stock.runtime.loop --mode paper
```

---

## 문서

- **`CLAUDE.md`** — 매매 룰 영구 메모 (불변 룰 6가지)
- **`docs/knowledge_base/`** — 영구 지식 베이스
  - `01_strategy_canslim_sepa.md` — 전략 원전 요약
  - `02_user_philosophy.md` — 매매 철학
  - `03_korean_market_rules.md` — KRX 거래 규정
  - `04_risk_management.md` — 리스크 룰북
  - `05_data_sources.md` — KIS/DART/pykrx 사용법
  - `06_glossary.md` — 용어 사전
  - `07_decision_log.md` — 의사결정 기록
  - `08_reading_list.md` — 학습 자료

---

## 개발 단계

- [x] **Phase 0** — 도메인 학습 + 지식 베이스 작성
- [x] **Phase 1** — 스캐폴딩 + KIS PoC
- [x] **Phase 2** — 인프라 (어댑터/데이터/리스크/실행)
- [x] **Phase 3** — 백테스트 + v1 전략
- [x] **Phase 4** — 운영 루프 + 모니터링 (90일 페이퍼 운영 필요)
- [x] **Phase 5** — Docker + CI/CD (AWS 배포 사용자 진행)
- [ ] **Phase 6** — 실거래 게이트 통과 후 전환

---

## 기술 스택

Python 3.12 / KIS Developers API / OpenDartReader / pykrx / vectorbt / SQLite + Parquet / APScheduler / python-telegram-bot / Docker / AWS Lightsail
