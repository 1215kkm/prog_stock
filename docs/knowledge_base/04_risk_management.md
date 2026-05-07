# 리스크 관리 룰북

이 문서의 룰은 **모든 주문이 통과해야 하는 게이트**다. 전략(`strategies/`)이 어떤 신호를 내든 이 룰을 깨는 주문은 거부된다. 구현은 `src/prog_stock/risk/guard.py`(상태 게이트)와 `src/prog_stock/risk/sizing.py`(포지션 크기)에 위치한다.

원칙: **1회 손실로 시스템이 망가지지 않도록 한다.** 수익은 옵션이지만 생존은 필수.

---

## 1. 손절 (Stop Loss)

우선순위 순서. 어느 하나라도 충족 시 즉시 청산.

### 1.1 하드 가격 손절: 진입가 -7%

- 매수 체결가 대비 -7% 도달 시 무조건 시장가 청산.
- **예외 없음.** 일회성 악재라거나 다음날 반등 가능성이라는 핑계로 보유 연장 금지.
- 미체결 위험: 하한가 잠금 시 손절 미체결 → 다음날 시초가 강제 청산 큐.

### 1.2 펀더멘털 꺾임: 사용자 핵심 룰

- 보유 종목의 새 분기 보고서에서 **매출 또는 영업이익이 YoY 마이너스로 전환** 시 즉시 시장가 청산.
- 보고서 인지 시점은 DART 공시 후 다음 영업일 오픈에 반영.
- v1 디폴트: 1분기만 마이너스여도 청산 (강한 룰).
- 백테스트 후 "2분기 연속 마이너스" 룰과 비교 → 더 나은 쪽 채택. 결정은 `07_decision_log.md`에 기록.

### 1.3 추세 이탈

- 종가 < 50일 이동평균 5거래일 연속 → 청산.
- 종가 < 200일 이동평균 → 즉시 청산.

### 1.4 트레일링 스탑

- 보유 후 +20% 이상 상승 시 활성화.
- 활성화 후: 보유 기간 중 최고가 대비 -10% 도달 시 청산.
- 이익 확정용. 끝까지 들고 가다 큰 수익 토해내는 패턴 방지.

### 1.5 시장 필터 (보유 종목 영향)

- 코스피200 지수 < 200MA → **신규 매수 중단**.
- 보유 종목은 위 1.1~1.4 룰로 개별 청산 결정 (시장 약세라고 일괄 청산 안 함).

### 손절 후 재매수 금지

- 1.1로 손절된 종목은 **30거래일간 재매수 금지** (추격 회피, 물타기 방지).
- 1.2로 손절된 종목은 다음 분기 보고서에서 다시 성장 전환 확인 시까지 재매수 금지.

---

## 2. 포지션 사이징

### 종목당 리스크 (Risk-Based Sizing)

자본의 **1.5%만 단일 종목 손실로 허용**.

```
계산:
  position_size_krw = (account_equity × 0.015) / 0.07
                    ≈ account_equity × 21.4%

예: 자본 1,000만원
  position_size_krw = 1,000만 × 0.015 / 0.07 ≈ 214만원
  진입가 -7% 손절 시 손실 = 214만 × 0.07 ≈ 15만원 = 자본의 1.5%
```

### 동시 보유 제한

- **최대 5종목 동시 보유**. (목적: 분산 + 관리 복잡도 제어)
- 단일 종목 자본 비중 25% 상한 (위 사이징과 별개의 캡).
- 자본 1,000만 × 5종목 × 21.4% = 107% → 100% 도달 시 신규 매수 중단(레버리지 미사용).

### 카나리 모드 (신규 전략 첫 30거래일)

- 새 전략 또는 새 자본은 첫 30거래일 동안 **자본의 1%만 운용**.
- 기간 통과 + 백테스트 대비 슬리피지 오차 X% 이내 → 자동으로 100% 자본으로 승격.

---

## 3. 일일 / 주간 / 전체 한도

### 일일 손실 한도 (Daily Loss Limit)

- 당일 누적 -3% 도달 시 **당일 매매 중단**. 다음날 정상 재개.
- 목적: 변동성 큰 날 연속 손절로 -10% 같은 큰 일중 낙폭 방지.

### 최대 낙폭 (Maximum Drawdown, MDD)

- 자본 고점 대비 **-15% 도달 시 전략 자동 정지** + 텔레그램 긴급 알림.
- 정지 해제는 **수동 결정** (사용자가 텔레그램으로 승인). 자동 재개 금지 — 시스템이 잘못된 환경에 있을 수 있음.

### 신규 매수 잠금 조건 (요약)

다음 중 어느 하나라도 충족 시 신규 매수 중단:
- 일일 손실 -3% 도달
- 자본 고점 -15% 도달 (이 경우 전략 전체 정지)
- 코스피200 < 200MA
- 미체결 주문 10건 이상
- 1분 내 잔고 변동 5% 이상 (이상치 — 즉시 정지 + 알림)

---

## 4. Kill Switch

운영자(사용자)가 어디서나 즉시 시스템을 멈출 수 있어야 한다.

### 텔레그램 명령

```
/stop  → 전 포지션 시장가 청산 + 전략 정지 + 확인 메시지
/halt  → 신규 매수만 중단, 보유는 유지 (덜 강한 정지)
/resume → 정지 해제 (수동 승인 필요한 정지에서만)
```

### 자동 Kill Switch

- 동일 종목 연속 5회 주문 실패 → 해당 종목 매매 잠금
- API 토큰 갱신 3회 연속 실패 → 시스템 정지 + 알림
- 데이터 피드 30초 끊김 → 신규 매수 중단

### 멱등성

- 모든 주문에 클라이언트 측 idempotency key 부여.
- 네트워크 오류 시 재시도 안전.

---

## 5. 리스크 가드 통합 게이트

`src/prog_stock/risk/guard.py`는 모든 신규/청산 주문 전 다음 순서로 검증:

```python
def gate(order: Order, ctx: Context) -> Decision:
    # 시스템 상태
    if ctx.kill_switch_engaged: return REJECT
    if ctx.daily_loss >= DAILY_LIMIT: return REJECT
    if ctx.drawdown >= MDD_LIMIT: return REJECT_AND_STOP

    # 시간/시장
    if not ctx.is_trading_window(order.symbol): return REJECT
    if ctx.in_call_auction and order.type == MARKET: return REJECT

    # 종목 상태
    if not ctx.is_tradeable(order.symbol):  # VI/거래정지/관리종목
        return REJECT
    if ctx.is_locked_limit(order.symbol):   # 상하한가 잠금
        return REJECT_OR_QUEUE_NEXT_OPEN

    # 포지션/자본
    if order.side == BUY:
        if ctx.market_filter_off: return REJECT  # 코스피200 < 200MA
        if ctx.symbol_in_cooldown(order.symbol): return REJECT  # 30거래일
        if ctx.open_positions >= MAX_POSITIONS: return REJECT
        if order.size_krw > ctx.available_cash: return REJECT
        if order.size_krw > ctx.equity * MAX_POSITION_PCT: return REJECT

    # 이상치
    if ctx.recent_balance_change_pct > 0.05: return REJECT_AND_HALT
    if ctx.pending_orders >= 10: return REJECT_AND_HALT

    return APPROVE
```

이 게이트가 거부한 모든 주문은 SQLite와 텔레그램에 기록.

---

## 6. 손익비 / 승률 목표

전략 평가 기준 (백테스트 + 페이퍼):

| 지표 | 최소 합격선 | 목표 |
|---|---|---|
| 승률 (Win Rate) | 35% 이상 | 45%+ |
| 평균 손익비 (Avg Win / Avg Loss) | 2.0 이상 | 2.5+ |
| Profit Factor (총이익/총손실) | 1.5 이상 | 2.0+ |
| 연환산 Sharpe Ratio | 0.8 이상 | 1.2+ |
| Sortino Ratio | 1.0 이상 | 1.5+ |
| 최대 낙폭 (MDD) | -25% 이내 | -15% 이내 |
| 평균 보유 기간 | 20~60일 | 30~45일 |

**중요**: 승률보다 **손익비**가 더 중요. 미너비니는 승률 50% 미만으로도 큰 수익을 낸다 — 평균 이익이 평균 손실의 3배 이상이기 때문.

---

## 7. 세후 P&L 계산

세전 수익률에 속지 않기 위해 매 거래·일·월 단위로 다음을 별도 표시:

```
거래별:
  gross_pnl     = (sell_px - buy_px) × qty
  commission    = (buy_px + sell_px) × qty × 0.00015
  tax_sell      = sell_px × qty × 0.0018
  net_pnl       = gross_pnl - commission - tax_sell
  net_return_pct = net_pnl / (buy_px × qty)
```

리포트는 항상 net 기준으로 보여준다. gross는 디버깅/검증용.

---

## 8. 운영 체크리스트 (매일)

시스템이 자동으로 실행하고 텔레그램에 송부.

### 06:00 — 사전 데이터 갱신
- [ ] DART 신규 분기 보고서 인지
- [ ] 거래정지/관리종목 갱신
- [ ] 화이트리스트 재생성
- [ ] 펀더멘털 꺾임 종목 청산 큐 등록

### 08:50 — 사전 점검 리포트
- [ ] 오늘 매수 후보 종목 (n개)
- [ ] 오늘 청산 예정 종목 (보유 + 룰 트리거)
- [ ] 잔여 일일 손실 한도
- [ ] 잔여 MDD 한도
- [ ] 시장 필터 상태 (코스피200 vs 200MA)

### 09:00 ~ 15:30 — 운영
- 위 모든 가드레일 활성

### 16:00 — 일일 리포트
- [ ] 당일 매매 내역
- [ ] 세후 P&L
- [ ] 잔고 스냅샷
- [ ] 다음 영업일 워치리스트

---

## 9. 변경 시 로그 필수

이 문서의 수치 파라미터(예: -7% 손절, -3% 일일 한도, 1.5% 종목 리스크) 변경 시 반드시 `07_decision_log.md`에 기록:
- 변경일
- 변경 전/후 값
- 근거 (백테스트 결과 링크, 데이터)
- 결정자

원칙(불변): 펀더멘털 꺾임 즉시 청산, 물타기 금지, 동시호가 시장가 금지 — 이 셋은 **수치 조정 무관, 룰 자체 변경 금지**.
