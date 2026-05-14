# CLAUDE.md — prog_stock 매매 룰 영구 메모

이 파일은 매 Claude Code 세션이 자동 로드한다. **사용자가 공부한 트레이딩 원칙을 잊지 않기 위한 핵심 룰 요약**이다. 더 자세한 근거는 `docs/knowledge_base/`를 참조.

---

## 시스템 정체성

- **이름**: prog_stock
- **목적**: 한국 주식 자동매매 (모의투자 → 실거래 자동 게이트)
- **운영 환경**: 클라우드 24시간 (AWS Lightsail Docker)
- **언어**: Python 3.12 (uv)
- **증권사 API**: KIS Developers (한국투자증권)
- **개발 브랜치**: `claude/stock-trading-automation-NDQpx`

---

## 매매 철학 (절대 변경 불가)

> **매출과 영업이익이 늘어나는 구간에서만 투자한다. 매출 또는 영업이익이 꺾이면 즉시 손절한다. 바닥은 예측하지 않는다.**

이 철학은 윌리엄 오닐(CAN SLIM) + 마크 미너비니(SEPA) 60년간 검증된 프레임워크와 일치한다.

자세한 원전: `docs/knowledge_base/01_strategy_canslim_sepa.md`
사용자 명시 철학: `docs/knowledge_base/02_user_philosophy.md`

---

## 불변 룰 (백테스트 결과와 무관하게 변경 금지)

1. **펀더멘털 꺾임 즉시 청산**: 보유 종목의 새 분기 보고서에서 매출 또는 영업이익이 YoY 마이너스로 전환되면 즉시 시장가 청산. 이유 따지지 않음.
2. **하드 가격 손절 -7%**: 진입가 대비 -7% 도달 시 무조건 청산. 예외 없음.
3. **물타기 금지**: 손실 종목에 자본 추가 투입 절대 금지.
4. **30거래일 재매수 금지**: 손절된 종목은 30거래일간 재매수 금지(추격 회피).
5. **동시호가 시장가 금지**: 08:30~09:00, 15:20~15:30에는 지정가만.
6. **바닥 예측 금지**: 하락 추세 종목은 추세 반전 신호(50/200MA 정렬, 신고가 돌파, 거래량 동반) 후에만 매수 후보.

수치 파라미터(예: -7%인지 -8%인지, 분기 1번인지 2번 연속인지)는 백테스트 후 조정 가능. 단 `07_decision_log.md`에 변경 기록 필수.

---

## v1 전략 — 한국형 CAN SLIM + SEPA

### 펀더멘털 필터 (DART 분기 보고서)
- F1. 직전 4분기 매출 모두 YoY > 0
- F2. 직전 4분기 영업이익 모두 YoY > 0
- F3. 최근 분기 영업이익 YoY ≥ 25%
- F4. 최근 3년 연간 영업이익 CAGR ≥ 20%
- F5. 직전 4분기 모두 영업이익 > 0
- F6. 시가총액 ≥ 1,000억

### 기술적 필터 (Minervini Trend Template)
- T1. 종가 > 50MA > 150MA > 200MA
- T2. 200MA 우상향 (최근 1개월)
- T3. 종가 ≥ 52주 최고가의 75%
- T4. 종가 ≥ 52주 최저가의 130%
- T5. 코스피200 대비 6개월 수익률 상위 30%
- M (Market filter). 코스피200 > 200MA일 때만 신규 매수

### 종목 풀
코스피200 + 코스닥150 → 관리/거래정지/투자위험·경고/단기과열/ETN/ETF/외국인한도임박/VI 발동 중 모두 제외.

### 진입
신고가 돌파 + 거래량 ≥ 20일 평균 ×1.5

### 청산 우선순위
1. 진입가 -7% 손절
2. **펀더멘털 꺾임 즉시 청산**
3. 50MA 5일 연속 이탈 또는 200MA 즉시 이탈
4. 트레일링 스탑 (+20% 후 전고 -10%)
5. 시장 필터 OFF 시 신규 매수만 중단

---

## 리스크 가드 (모든 주문 통과 필수)

- 종목당 자본 리스크 1.5% (= 자본의 약 21.4% 포지션 × -7% 손절)
- 동시 보유 최대 5종목, 단일 종목 자본 25% 상한
- 일일 손실 -3% 시 당일 매매 중단
- MDD -15% 시 전략 자동 정지 + 텔레그램 알림 + **수동 승인** 후 재개
- 카나리: 신규 전략 첫 30거래일 자본 1%만 운용
- Promotion gate: paper 90일 무중단 + 백테스트 vs 라이브 슬리피지 X% 이내 → live 자동 승격

세부: `docs/knowledge_base/04_risk_management.md`

---

## 한국 시장 특수 규칙

- 거래 시간 09:00~15:30, 동시호가 08:30~09:00 / 15:20~15:30
- 일일 가격 제한 ±30% (상하한가 잠금 시 손절 미체결 → 다음날 시초가 강제 청산)
- VI 발동 중 종목은 신규 주문 거부
- 매도 거래세 0.18% (코스피·코스닥)
- 결제 T+2

세부: `docs/knowledge_base/03_korean_market_rules.md`

---

## 기술 스택 (요약)

| 영역 | 라이브러리 |
|---|---|
| KIS API | `python-kis` (어댑터 패턴으로 격리) |
| 펀더멘털 데이터 | `OpenDartReader` |
| 시세 데이터 | `pykrx` (수정주가 `adjusted=True` 필수) |
| 거래일 캘린더 | `exchange_calendars` (XKRX) |
| 백테스트 | `vectorbt` |
| 라이브 운영 | 자체 이벤트루프 (백테스트와 의도적 이원화) |
| 저장소 | SQLite (거래/포지션) + Parquet (시세) |
| 스케줄 | APScheduler |
| 알림/제어 | `python-telegram-bot` (`/stop` `/status` `/positions` `/today`) |
| 배포 | Docker + AWS Lightsail |
| 시크릿 | AWS SSM Parameter Store |

세부: `docs/knowledge_base/05_data_sources.md`

---

## 디렉터리 구조 (목표)

```
prog_stock/
├── docs/knowledge_base/  ← 영구 지식 베이스 (불변 + 결정 로그)
├── CLAUDE.md             ← 매 세션 자동 로드
├── src/prog_stock/
│   ├── brokers/          (port.py, kis_adapter.py, paper_adapter.py)
│   ├── data/             (universe, fundamentals, history, calendar)
│   ├── strategies/       (base, canslim_sepa, dual_momentum, volatility_breakout)
│   ├── risk/             (guard, sizing)
│   ├── execution/        (order_manager)
│   ├── runtime/          (mode, scheduler, loop, state, logging_config)
│   ├── agents/           (bounds, base, researcher, auditor, regime, portfolio, orchestrator)
│   ├── monitoring/       (telegram_bot, morning_report)
│   ├── storage/          (db)
│   ├── backtest/         (runner)
│   ├── tools/            (cli, backfill_*)
│   └── config.py
├── tests/
├── notebooks/
├── configs/
└── docker/
```

---

## 개발 단계 (현재 위치 표시)

- [x] **Phase 0** — 도메인 학습 + 지식 베이스 작성
- [x] **Phase 1** — 스캐폴딩 + KIS PoC
- [x] **Phase 2** — 인프라 (어댑터/데이터/리스크/실행)
- [x] **Phase 3** — 백테스트 + v1 전략
- [x] **Phase 4** — 운영 루프 + 모니터링 (90일 페이퍼 운영 필요)
- [x] **Phase 5** — Docker + CI/CD (AWS 배포 사용자 진행)
- [x] **Phase 6** — 멀티 에이전트 자율 시스템 (Researcher / Auditor / Regime / Portfolio)
- [ ] **Phase 7** — 실거래 게이트 통과 후 전환 ← *Promotion gate 자동*

---

## 멀티 에이전트 자율 시스템 (Phase 6)

매일 16:30 (`daily_pipeline`) + 매주 일요일 23:00 (`weekly_pipeline`) 자동 실행:

1. **Researcher**: 파라미터 그리드 백테스트 → 더 나은 후보 발견 시 카나리(자본 1%, 30일) 자동 시작
2. **Auditor**: 거래 일지 분석 → 5연속 손절 시 **자동 HALT**, 승률 저하 알림
3. **Regime Detector**: KOSPI200 vs 200MA → 상승장 100% / 횡보 50% / 하락 25% 자본 자동 조절
4. **Portfolio Manager**: 멀티 전략(CAN SLIM + 듀얼 모멘텀 + 변동성 돌파) 자본 비중 90일 성과 기반 자동 재배분

**자율성 안전장치 (`agents/bounds.py`)**:
- 불변 룰 6가지(아래) 코드 레벨 잠금 — 어떤 에이전트도 약화 불가
- 수치 파라미터는 PARAM_BOUNDS 경계 내에서만 변경 (예: 손절 -5% ~ -10%)
- 경계 외 변경 시도는 Orchestrator에서 자동 REJECTED
- 모든 결정 텔레그램 자동 전송 — 사용자 `/stop`으로 언제든 차단

---

## Claude 세션 작업 시 행동 지침

1. **이 파일을 매 세션 자동 읽음.** 변경 시 신중하게 — 룰 약화 금지.
2. **불변 룰 위배되는 코드는 작성하지 않는다.**
   - 예: 손실 종목 추가 매수 코드 X
   - 예: 동시호가 시장가 주문 코드 X
   - 예: -7% 손절 우회 옵션 추가 X
3. **수치 파라미터 변경 시** 반드시 `07_decision_log.md`에 기록 후 변경.
4. **새 자료 학습 시** 해당 문서에 반영하고 `08_reading_list.md`에 출처 추가.
5. **테스트 우선**: 리스크 가드는 단위 테스트 100% 커버.
6. **개발 브랜치 고정**: `claude/stock-trading-automation-NDQpx`. 다른 브랜치에 푸시 금지.

---

## 비용 (운영 기준)

- KIS API / DART API / 텔레그램 봇: **무료**
- 클라우드 (AWS Lightsail): 월 약 7,000원
- 실거래 시 수수료: 매수·매도 각 ~0.014%, 매도 거래세 0.18%

---

## 한 줄로 요약

> **성장하는 회사를 추세에 따라 매수하고, 꺾이면 무조건 손절한다.**
