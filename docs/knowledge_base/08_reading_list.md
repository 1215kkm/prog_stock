# 학습 자료 (Reading List)

이 시스템 운영자(사용자 + Claude)가 도메인 전문성을 유지하기 위한 추천 자료. 우선순위 순서.

---

## 1. 필독 — 전략 원전

### 윌리엄 오닐 (William O'Neil)
- ***How to Make Money in Stocks*** (4th ed., 2009) — CAN SLIM 정본. 한국어판: 『최고의 주식 최적의 타이밍』
- *24 Essential Lessons for Investment Success*

### 마크 미너비니 (Mark Minervini)
- ***Trade Like a Stock Market Wizard*** (2013) — SEPA, VCP, Trend Template. 한국어판: 『주식시장의 마법사들처럼 매매하라』
- *Think and Trade Like a Champion* (2017) — 실전 사례
- *Mindset Secrets for Winning* (2019) — 심리

### 잭 슈웨거 (Jack Schwager)
- *Market Wizards* 시리즈 — 거장들 인터뷰. 특히 *Unknown Market Wizards* (2020) 추천: 개인 트레이더 사례.

### 스탠 와인스타인 (Stan Weinstein)
- *Secrets for Profiting in Bull and Bear Markets* (1988) — Stage 분석 원전. 미너비니가 자주 인용.

---

## 2. 한국 시장 자료

### KRX 공식
- **KRX 매매거래제도 안내**: https://global.krx.co.kr/contents/GLB/05/0501/0501010101/GLB0501010101.jsp
- **KRX 시장운영 매뉴얼** (PDF): KRX 홈페이지 자료실
- **KIND 기업공시채널**: https://kind.krx.co.kr — 종목 상태 확인
- **DART 사용자 매뉴얼**: https://opendart.fss.or.kr

### 한국 자동매매 블로그/커뮤니티
- **TG's Programming Blog**: https://tgparkk.github.io/ — 한국투자증권 API 자동매매 시리즈
- **wikidocs.net "파이썬을 이용한 한국/미국 주식 자동매매 시스템"**: https://wikidocs.net/book/7995
- **퀀티랩 블로그**: https://blog.quantylab.com — 한국 시장 퀀트 분석

### KIS Developers 공식
- API 포털: https://apiportal.koreainvestment.com/intro
- 공식 샘플 GitHub: https://github.com/koreainvestment/open-trading-api
- python-kis (커뮤니티): https://github.com/Soju06/python-kis

### DART
- OpenDartReader: https://github.com/FinanceData/OpenDartReader
- pykrx: https://github.com/sharebook-kr/pykrx

---

## 3. 트레이딩 시스템 일반

### 알고리즘 트레이딩
- *Advances in Financial Machine Learning* — Marcos López de Prado (2018) — 백테스트 함정·교차검증
- *Quantitative Trading* — Ernie Chan (2008)
- *Algorithmic Trading and DMA* — Barry Johnson — 주문 실행 마이크로구조

### 리스크 관리
- *The New Trading for a Living* — Alexander Elder
- QuantInsti 블로그: https://blog.quantinsti.com/trading-risk-management/

### 백테스트 도구
- vectorbt 공식 문서: https://vectorbt.dev/
- backtrader 공식 문서: https://www.backtrader.com/

---

## 4. 한국 트레이더 영상/콘텐츠

(사용자가 보고 영감 받은 자료를 추가 — 지식 보강용)

- *주식천재 유튜브* — 사용자 매매 철학 형성에 영감 (`02_user_philosophy.md` 참조). 핵심: "매출·영업이익 성장 구간에만, 꺾이면 즉시 손절, 바닥 예측 금지". 추가 영상 시청 시 인사이트를 `07_decision_log.md`에 기록.
- 슈퍼개미 김정환 / 박민수(샌드타이거샤크) 등의 인터뷰 — 한국형 성장주 추세추종 사례

---

## 5. 시장 사이클 / 매크로

- *Mastering the Market Cycle* — Howard Marks (2018)
- *Stocks for the Long Run* — Jeremy Siegel — 장기 시장 통계
- 한국은행 통화신용정책보고서 (분기) — 매크로 환경 점검

---

## 6. 코드/엔지니어링 자료

### Python 트레이딩 인프라
- *Python for Finance* — Yves Hilpisch (2nd ed.)
- *Building Algorithmic Trading Systems* — Kevin Davey

### Cloud / 운영
- AWS Lightsail 가이드: https://aws.amazon.com/lightsail/
- Docker 공식 튜토리얼: https://docs.docker.com/get-started/

---

## 7. 학술 논문 / 리서치

(시간 날 때 정독)

- Fama & French, *Common Risk Factors in the Returns on Stocks and Bonds* (1993) — 팩터 모델
- Jegadeesh & Titman, *Returns to Buying Winners and Selling Losers* (1993) — 모멘텀 효과 검증
- López de Prado, *The 10 Reasons Most Machine Learning Funds Fail* (2018)
- 한국 시장 변동성 돌파 전략 실증 분석 (한국증권학회지 등) — 검색 후 추가

---

## 학습 진행 추적

새 자료 학습 시:
1. 핵심 인사이트를 해당 지식 문서(`01_~05_`)에 반영.
2. 변경 사항이 전략·파라미터에 영향 주면 `07_decision_log.md`에 기록.
3. 본 파일에 출처 추가.

이로써 "공부한 거 까먹지 않게"가 시스템적으로 보장된다.
