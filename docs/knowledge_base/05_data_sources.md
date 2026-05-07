# 데이터 소스 — KIS / DART / pykrx

자동매매 시스템에 필요한 모든 데이터의 출처, 사용법, 한도, 함정을 정리.

---

## 1. KIS Developers (한국투자증권 Open API)

### 무엇인가
- 한국투자증권이 공식 제공하는 REST + WebSocket API.
- **모의투자 계좌 + 실거래 계좌 모두 지원**, 동일 인터페이스.
- 무료, 개인 계좌만 있으면 가입 가능.

### 가입 절차
1. 한국투자증권 비대면 계좌 개설 (영업일 24시간, 약 10분).
2. https://apiportal.koreainvestment.com 접속 → 회원가입.
3. "API 신청" → app key / app secret 발급.
4. 모의투자 신청 (별도 신청 — 분기마다 갱신 필요).

### 주요 엔드포인트

| 분류 | 용도 | 호출 방식 |
|---|---|---|
| 인증 | OAuth 토큰 발급/갱신 | REST POST |
| 계좌 | 잔고/손익/체결 조회 | REST GET |
| 주문 | 매수/매도/정정/취소 | REST POST |
| 시세 | 일봉/분봉/현재가/호가 | REST GET |
| 실시간 | 체결가/호가/체결통보 | WebSocket |

### Rate Limit
- **초당 20 요청**(실거래) / **초당 2 요청**(모의투자).
- 시스템: 토큰버킷 알고리즘으로 제한 준수 (`execution/order_manager.py`).
- 초과 시 일시적 차단 → 30초 후 재시도.

### 토큰
- `access_token` 유효기간: **24시간**. 만료 직전 자동 갱신.
- `app_key`/`app_secret`은 **AWS SSM Parameter Store**에 저장 (코드에 절대 하드코딩 금지).

### 모의투자 vs 실거래 차이
- 모의투자: 가상 자본(기본 1억), 실시간 시세 동일, 체결은 KIS 모의 엔진 사용 (실제 호가창과 약간 차이).
- **분기 단위로 모의투자 신청 갱신** 필요. 만료 시 잔고 초기화. 매 분기 첫 영업일 자동 재신청 로직 필요.

### 라이브러리: `python-kis` (Soju06)

GitHub: https://github.com/Soju06/python-kis

```python
from pykis import PyKis

# 모의투자
kis = PyKis(
    appkey=appkey,
    appsecret=appsecret,
    account="50068923-01",
    virtual_account=True,  # 모의
)

# 실거래
kis = PyKis(
    appkey=appkey,
    appsecret=appsecret,
    account="50068923-01",
    virtual_account=False,
)

# 잔고
balance = kis.account.balance()

# 주문
kis.order.buy("005930", quantity=10, price=70000)  # 삼성전자 10주 70,000원 지정가
```

### 어댑터 패턴 (필수)

`python-kis`에 직접 의존하지 말고 **`brokers/port.py`의 `BrokerPort` 추상**을 통해 격리:

```python
class BrokerPort(Protocol):
    def place_order(self, order: Order) -> OrderId: ...
    def cancel(self, order_id: OrderId) -> None: ...
    def positions(self) -> list[Position]: ...
    def balance(self) -> Balance: ...
    def quote(self, symbol: str) -> Quote: ...
    def subscribe(self, symbols: list[str]) -> AsyncIterator[Tick]: ...
```

`brokers/kis_adapter.py`는 그 구현체. 라이브러리 변경 시 어댑터만 교체.

### 함정
1. **계좌번호 형식**: `12345678-01` 처럼 종합계좌번호-상품코드. 둘 다 필요.
2. **시간 포맷**: KIS는 한국 시간(KST) 기준. 시스템 타임존 항상 KST로 고정.
3. **휴일 호출**: 휴장일에 시세 조회 시 빈 응답 또는 전영업일 데이터 반환 — 캘린더 검증 후 호출.
4. **체결 통보**: WebSocket 끊김 시 자동 재구독, 재구독 직후 누락 체결을 REST로 폴링해서 보강.

### 공식 문서
- API 포털: https://apiportal.koreainvestment.com/intro
- 공식 샘플: https://github.com/koreainvestment/open-trading-api

---

## 2. DART OpenAPI (전자공시 / 분기 실적)

### 무엇인가
- 금융감독원 운영 전자공시 시스템(DART)의 OpenAPI.
- 상장사 분기/반기/연간 보고서 자동 수집.
- 무료. API 키만 발급받으면 사용.

### 가입 절차
1. https://opendart.fss.or.kr 접속 → 회원가입.
2. "OpenAPI 인증키 신청" → 발급 (즉시).
3. 일일 호출 한도: **20,000건/일** (충분).

### 주요 엔드포인트

| 용도 | 엔드포인트 | 비고 |
|---|---|---|
| 회사 코드 매핑 | `/api/corpCode.xml` | 종목코드 → DART 고유번호 |
| 사업보고서 목록 | `/api/list.json` | 분기/반기/연간 보고서 |
| 재무제표 | `/api/fnlttSinglAcntAll.json` | 매출/영업이익/순이익 |

### 라이브러리: `OpenDartReader`

GitHub: https://github.com/FinanceData/OpenDartReader

```python
import OpenDartReader

dart = OpenDartReader(api_key)

# 삼성전자 분기 매출/영업이익 (재무제표)
fs = dart.finstate("005930", 2024, reprt_code="11013")  # 11013 = 1분기
# reprt_code: 11011=연간, 11012=반기, 11013=1분기, 11014=3분기

# 분기 보고서 자체 (텍스트)
report = dart.report("005930", "사업의내용", 2024, "11013")
```

### 분기 코드
- `11011`: 사업보고서 (연간, 12월 결산 기준 다음해 3월 말 제출)
- `11012`: 반기보고서 (8월 말)
- `11013`: 1분기 보고서 (5월 중순)
- `11014`: 3분기 보고서 (11월 중순)

### 함정
1. **공시 지연**: 분기 종료 후 **45일 이내** 제출 — 백테스트 시 보고서 발표일 이후에만 데이터를 사용해야 look-ahead bias 안 남.
2. **정정공시**: 동일 분기 보고서가 여러 번 정정될 수 있음. 정정 후 데이터 사용. 단, 라이브에서는 정정 전 데이터로 매매했음을 인지.
3. **연결 vs 별도**: 보통 **연결 재무제표** 사용 (자회사 포함). `fs_div="CFS"` 명시.
4. **금융업 특수성**: 은행/보험은 매출 정의가 다름 — v1에서는 금융업 제외 권장.

### 시스템 모듈
`src/prog_stock/data/fundamentals.py`가 매일 06:00 다음 작업:
1. 신규 공시 인지 (전일 공시 신호).
2. 4분기 매출/영업이익 시계열 캐시 갱신 (`data/cache/fundamentals.parquet`).
3. **꺾임 감지**: 최신 분기에서 매출 또는 영업이익 YoY 마이너스 전환 종목 → 청산 큐 등록.

---

## 3. pykrx (한국 시세/시장 데이터)

### 무엇인가
- KRX 공식 페이지 크롤링 기반 Python 라이브러리.
- 일봉/거래대금/시가총액/외국인 보유율/관리종목 상태 등.
- 무료, 인증 불필요.

GitHub: https://github.com/sharebook-kr/pykrx

```python
from pykrx import stock

# 5년치 수정주가 일봉 (수정주가 핵심!)
df = stock.get_market_ohlcv("20200101", "20250101", "005930", adjusted=True)

# 코스피200 구성종목
codes = stock.get_index_portfolio_deposit_file("1028", "20250101")  # 코스피200

# 시가총액
mcap = stock.get_market_cap("20250101")

# 관리종목
mgmt = stock.get_market_stock_management()
```

### 함정
1. **`adjusted=True` 필수**: 미사용 시 배당락/액면분할 미보정 → 백테스트 결과 거짓.
2. **속도**: 크롤링 기반이라 느림. 매번 호출 X, **parquet 캐시** 필수 (`data/history.py`).
3. **휴장일**: KRX 휴장일에 호출 시 빈 데이터프레임. 캘린더 사전 확인.

### 시스템 모듈
`src/prog_stock/data/history.py`:
- 종목별 일봉을 parquet로 캐시 (`data/cache/ohlcv/{symbol}.parquet`).
- 매일 16:00 신규 일봉 추가.
- 첫 실행 시 5년치 일괄 다운로드 (시간 30분~1시간 소요).

---

## 4. 거래일 캘린더: `exchange_calendars`

KRX 정규 휴장일을 매년 자동 갱신해주는 라이브러리.

```python
import exchange_calendars as xcals
xkrx = xcals.get_calendar("XKRX")
xkrx.is_session("2025-05-05")  # False (어린이날)
xkrx.next_session("2025-05-04")  # 다음 영업일
```

`src/prog_stock/data/calendar.py`에서 래핑.

---

## 5. 텔레그램 봇

### 가입
1. 텔레그램에서 `@BotFather`에게 `/newbot` → 봇 이름 입력 → **bot token** 발급.
2. 본인 계정 chat_id 확인: `https://api.telegram.org/bot{TOKEN}/getUpdates` 호출 후 직접 메시지 보내고 응답에서 `chat.id` 추출.

### 라이브러리: `python-telegram-bot`

```python
from telegram.ext import Application, CommandHandler

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("status", handle_status))
app.add_handler(CommandHandler("stop", handle_kill_switch))
app.run_polling()
```

### 보안
- bot token은 SSM Parameter Store.
- chat_id 화이트리스트 — 인가된 사용자만 명령 수신.

---

## 6. 데이터 갱신 일정 (요약)

| 시간 | 작업 | 모듈 |
|---|---|---|
| 매일 06:00 | DART 신규 공시 수집 + 화이트리스트 재생성 | `data/fundamentals.py`, `data/universe.py` |
| 매일 16:00 | 신규 일봉 추가 | `data/history.py` |
| 매월 1일 | exchange_calendars 갱신 | `data/calendar.py` |
| 매분기 | 모의투자 계좌 갱신 | `brokers/kis_adapter.py` |
| 매년 1월 | KRX 거래 규정 점검 (수동) | (사람이 함) |

---

## 7. 환경변수 / 시크릿 (`.env` 또는 SSM)

```
KIS_APP_KEY=...
KIS_APP_SECRET=...
KIS_ACCOUNT_NUMBER=12345678-01
KIS_VIRTUAL=true              # 모의투자 / false=실거래
DART_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
DB_PATH=./data/prog_stock.db
LOG_LEVEL=INFO
```

`.env`는 **반드시 `.gitignore`**, 절대 커밋 금지. 실서비스는 SSM Parameter Store.

---

## 8. 데이터 디렉터리 구조

```
data/
├── cache/
│   ├── ohlcv/                  # 종목별 일봉 parquet
│   │   ├── 005930.parquet
│   │   └── ...
│   ├── fundamentals.parquet    # 전 종목 4분기 매출/영업이익 시계열
│   ├── universe/
│   │   └── 2025-05-07.parquet  # 일별 화이트리스트 스냅샷
│   └── market/
│       └── kospi200_index.parquet
├── prog_stock.db               # SQLite (거래/포지션/잔고)
└── logs/                       # 운영 로그
```

`.gitignore`에 `data/` 전체 등록.
