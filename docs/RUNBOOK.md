# 운영 매뉴얼 (RUNBOOK)

이 문서는 prog_stock을 처음부터 실거래까지 운영하는 절차서다. 단계별로 따라가면 된다.

---

## 0. 전제 조건

- 한국투자증권 비대면 계좌
- DART OpenAPI 계정 (https://opendart.fss.or.kr — 즉시 발급)
- 텔레그램 (`@BotFather`로 봇 생성)
- Python 3.12, uv 권장
- AWS 계정 (Phase 5 클라우드 배포 시)

---

## 1. 최초 설치 (한 번만)

```bash
git clone <repo>
cd prog_stock

# 의존성
uv sync --extra dev
# 또는: pip install -e ".[dev]"

# 환경변수
cp .env.example .env
# .env 편집:
#   KIS_APP_KEY=...        한국투자증권 API 포털에서 발급
#   KIS_APP_SECRET=...
#   KIS_ACCOUNT_NUMBER=12345678-01
#   KIS_VIRTUAL=true       모의투자 시작
#   DART_API_KEY=...       DART 발급 키
#   TELEGRAM_BOT_TOKEN=... BotFather 발급
#   TELEGRAM_CHAT_ID=...   본인 chat id

# pre-commit 활성화
pre-commit install
```

---

## 2. KIS 모의투자 잔고 확인 (PoC)

```bash
python -m prog_stock.poc.balance
```

출력 예:
```
모드: 모의투자
현금: 100,000,000원
평가금액: 0원
총자산: 100,000,000원
보유 종목 수: 0
```

이게 안 되면 `.env`의 KIS 키와 모의투자 신청 상태(분기 단위 갱신 필요) 확인.

---

## 3. 데이터 백필 (페이퍼 시작 전 1회 필수)

전략은 **5년치 일봉 + 분기 실적 + KOSPI200 지수**가 필요하다. 매일 운영 루프가 자동 갱신하지만 첫 실행 시 한 번 명시적으로 채워둬야 한다.

```bash
# 1) KOSPI200 지수 (3년)
python -m prog_stock.tools.backfill_market_index --years 3

# 2) 종목 풀 일봉 (5년) — 코스피200 + 코스닥150 약 350종목, 30분~1시간 소요
python -m prog_stock.tools.backfill_history --years 5

# 3) DART 분기 실적 (최근 2년)
python -m prog_stock.tools.backfill_fundamentals --years 2024,2025,2026
```

저장 위치: `data/cache/`

---

## 4. 백테스트 실행 (Phase 3)

```bash
python -m prog_stock.backtest.runner \
  --years 5 \
  --symbols 005930,000660,035420,051910
```

출력:
- `trades`: 총 거래 수
- `cagr`: 연환산 수익률
- `mdd`: 최대 낙폭
- `sharpe`: 샤프 비율
- `win_rate`, `profit_factor`

목표 수치 (`docs/knowledge_base/04_risk_management.md` 6번):
- Sharpe ≥ 0.8
- MDD > -25%
- Profit Factor ≥ 1.5

미달이면 전략 파라미터 조정 → `docs/knowledge_base/07_decision_log.md`에 기록.

---

## 5. Dry-run (Phase 2 인프라 검증, 1주)

전략 X. 시세 피드 + 가상 주문장부 인프라만 검증.

```bash
python -m prog_stock.runtime.loop --mode dry_run
```

별도 터미널에서:
```bash
python -m prog_stock.tools.cli status
python -m prog_stock.tools.cli today    # 사전점검 리포트
```

확인:
- 텔레그램 "🚀 prog_stock started" 수신
- 매일 08:50 사전점검 리포트 텔레그램 도착
- 매일 16:00 장마감 리포트 도착
- `data/logs/trading.log` 정상 기록
- 동시호가/레이트리밋 위반 0건

---

## 6. Paper 트레이딩 (Phase 4, ≥ 90일)

전략 ON. 가상 자본으로 실제 시장 데이터에 매매.

```bash
python -m prog_stock.runtime.loop --mode paper
```

이 단계는 **최소 90거래일 무중단 운영**해야 Phase 6(실거래) 자동 게이트가 열린다.

### 일일 체크 (매일 16:30)
```bash
python -m prog_stock.tools.cli status
```

### 텔레그램 명령
- `/status` — 현재 잔고/포지션
- `/positions` — 보유 상세
- `/today` — 오늘 매수 후보·예정 청산
- `/halt` — 신규 매수 잠금 (보유 유지)
- `/resume` — halt 해제
- `/stop` — 전 포지션 청산 + 시스템 정지 (수동 승인)

### 카나리 → 100% 자동 승격
- 첫 30거래일은 자본의 1%만 운용 (RuntimeState 자동 관리)
- 30일 통과 + 백테스트 슬리피지 오차 X% 이내 → 자동 100%

### 비상 정지
```bash
# 1) 텔레그램으로 /stop 또는
python -m prog_stock.tools.cli kill   # 확인 후 청산

# 2) 시스템 종료
docker compose down
# 또는: Ctrl+C in foreground process
```

---

## 7. 클라우드 배포 (Phase 5)

### 7.1 AWS Lightsail 인스턴스 생성

- $10/월 ($5도 가능하나 RAM 1GB 부족 위험): Ubuntu 22.04, 2GB RAM
- 고정 IP 부착
- SSH 키 다운로드

### 7.2 인스턴스 초기 설정

```bash
ssh -i prog_stock.pem ubuntu@<IP>

# Docker 설치
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
# 재로그인

# 코드 클론
sudo mkdir -p /opt/prog_stock
sudo chown ubuntu:ubuntu /opt/prog_stock
cd /opt/prog_stock
git clone <repo> .
cp .env.example .env
# .env 편집
```

### 7.3 시크릿: AWS SSM Parameter Store (권장)

```bash
# 로컬에서
aws ssm put-parameter --name /prog_stock/kis_app_key --value "..." --type SecureString
aws ssm put-parameter --name /prog_stock/kis_app_secret --value "..." --type SecureString
# ... 나머지 키
```

인스턴스 IAM Role에 `ssm:GetParameter` 부여하고 entrypoint에서 SSM에서 로드.

### 7.4 컨테이너 시작

```bash
RUN_MODE=paper docker compose up -d
docker compose logs -f
```

### 7.5 systemd로 부팅 자동 시작

```ini
# /etc/systemd/system/prog_stock.service
[Unit]
Description=prog_stock trader
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/prog_stock
Environment=RUN_MODE=paper
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable prog_stock
sudo systemctl start prog_stock
```

### 7.6 백업

매일 03:00 SQLite + parquet → S3 (cron):
```cron
0 3 * * * tar czf - /opt/prog_stock/data | aws s3 cp - s3://prog-stock-backup/$(date +\%F).tar.gz
```

---

## 8. 실거래 전환 (Phase 6, Promotion Gate)

### 게이트 자동 평가
```python
from prog_stock.runtime.mode import evaluate_promotion
# paper 90일 무중단 + Sharpe ≥ 0.8 + MDD > -20% + 백테스트 Profit Factor 드리프트 < 20%
```

### 게이트 통과 후

```bash
# .env 수정
KIS_VIRTUAL=false        # 실거래 전환

# 소액 시작 (예: 100만원 입금)
docker compose down
RUN_MODE=live docker compose up -d
```

### 첫 달 점검
- 매일 paper P&L vs live P&L 비교 (텔레그램 알림에 자동 포함)
- 둘이 ±오차 범위(±20%) 안이면 정상
- 벗어나면 즉시 `/stop` → 원인 분석 (슬리피지, 호가 미스, API 차이 등)

### 자본 점진 증액
- 1개월 무사고 → 200만원
- 3개월 무사고 → 500만원
- 6개월 무사고 → 1,000만원
- 1년 무사고 → 자유 결정

---

## 9. 트러블슈팅

### KIS API 토큰 만료
- 24시간 자동 갱신. 실패 시 텔레그램 알림.
- 수동 갱신: `python -m prog_stock.poc.balance`로 토큰 새로 받기.

### DART 호출 실패
- 일일 호출 한도(20,000건) 초과 가능 → 다음날 재시도.
- 분기 보고서 미존재 → 종목이 신규 상장이거나 결산월 다름.

### 모의투자 계좌 만료
- 분기 단위로 신청 갱신 필요. KIS 포털에서 매 분기 첫 영업일 재신청.

### 코스피200/코스닥150 구성 변경
- 매년 6월/12월 정기 변경 + 임시 변경 가능.
- universe.py가 매일 아침 재생성하므로 자동 반영.

### 휴장일 공휴일
- `exchange_calendars` 라이브러리가 자동 처리.
- 임시휴장 시 라이브러리 업데이트 필요: `pip install -U exchange-calendars`

### 시스템 행 (Hang) 의심
```bash
docker compose logs --tail 100
docker compose restart
```

상태 복원이 자동 (RuntimeState + paper_state.json + SQLite).

---

## 10. 정기 점검 (사용자가 사람으로 해야 할 것)

| 주기 | 항목 |
|---|---|
| 매일 | 텔레그램 일일 리포트 확인 |
| 매주 | `cli status`로 거래 내역 확인 |
| 매월 | `07_decision_log.md` 갱신 (변경사항 있을 시) |
| 매분기 | KIS 모의투자 갱신 (실거래는 불필요), 모의↔실거래 결과 비교 |
| 매년 1월 | KRX 거래 규정 변경 점검 (`03_korean_market_rules.md`) |
| 매년 1월 | 거래세율 / 양도세 룰 변경 점검 |

---

## 11. 한 줄 요약

> **백필 → dry_run 1주 → 백테스트 → paper 90일 → 게이트 통과 → live 100만원부터**

각 단계 통과 후만 다음 단계로 넘어간다. 단계 건너뛰지 않는다.
