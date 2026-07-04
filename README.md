# JB Compliance · CONTENT SAFEGUARD

> Team **JunBub** · JB금융그룹 Fin AI Challenge (지정주제 2 — 금융광고 사전심의 AI)

금융광고 문안을 **법령·심의기준·상품설명서 사실**과 대조하고, **규칙 기반 판정과
LLM 해석을 결합**해 **설명가능한 사전 검토**를 지원하는 콘솔.

핵심 차별점: 룰베이스가 적용범위를 자르고(상품군별 필수고지 카탈로그·법령 위임
사슬) 기계적 위반을 직접 판정하면, LLM은 *정리된 문제*만 해석한다(단정·오인 등
맥락 판단 + 전체 인상 종합). 모든 판정은 근거 조문 원문까지 추적된다.

이 앱은 결정론 fallback으로 심사를 대체하지 않는다. LLM 자격증명/Neo4j가 없으면
규칙으로 조용히 대체하지 않고 실패한다.

---

## 1. 실행 방법 (Quick Start)

### 요구 환경

- Python 3.11+ (개발은 3.13), Node.js 20+
- Neo4j 5.x (Aura 또는 self-hosted) — 정책 그래프·상품 그래프 저장소
- OpenAI API 키 (필수), Anthropic API 키 (Claude 판정 모델 선택 시)

### 환경 설정

```bash
cp .env.example .env
# .env 에 OPENAI_API_KEY / NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD 채우기
# (Claude 판정 모델을 쓰려면 ANTHROPIC_API_KEY 도)
```

`.env.example`에 모든 설정 항목과 기본값이 주석과 함께 정리되어 있다
(로컬 LLM 라우팅, 캄보디아 워크스페이스 2-DB, 이미지 생성 품질/타임아웃,
Track C 토글 등).

### 백엔드 (FastAPI, :8770)

```bash
pip install -r requirements.txt   # 또는 pyproject 기반 환경
uvicorn server:app --port 8770
```

### 프론트엔드 (Next.js 심사 콘솔, :3000)

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000 — /api/* 는 백엔드(:8770)로 프록시
```

### 정책 그래프 적재 (최초 1회, 워크스페이스별)

```bash
python3 policy_compiler.py --workspace-id graphcompliance_mvp_jb_20260530 --batch-size 16
python3 vocabulary_governance.py --workspace-id graphcompliance_mvp_jb_20260530 --batch-size 40
```

컴파일러가 만드는 정책 정렬 레이어:

```text
LegalClause/LegalChunk -> Premise -> PolicyHypernym
Premise -> ComplianceUnit -> CUEmbeddingProfile
ComplianceUnit -> CULegalElementProfile
ComplianceUnit -> HAS_SUBJECT_HYPERNYM -> PolicyHypernym
```

### CLI 단건 심사 (콘솔 없이 빠른 확인)

```bash
python3 review_ad.py --text "지난 3년간 조기상환 성공률이 높았던 ELS, 중위험 투자자에게 좋은 선택입니다."
```

---

## 2. 주요 기능

### 예선 (MVP)

- **심사 콘솔(3-pane)**: 광고 원문 하이라이트(심각도 색 + 물결 밑줄) · 위험 카드
  (개별 심사 Track A + 종합 심사 Track B) · 판정 상세(금감원 회답식
  정의→요건→결론→유보).
- **필수 고지 점검**: 상품군별 필수 고지를 그래프 카탈로그(`disc_*`)에서 데이터
  기반으로 산출, 광고 내 존재/부재 + 현저성(혜택 대비 표시 위계) 판정.
- **상품 사실 대조 (Product Fact Graph)**: 광고 주장(ClaimFact) ↔ 상품설명서/약관
  사실(ProductFact) 비교 — `SUPPORTED / CONTRADICTED / CONDITION_MISSING /
  PROMINENCE_INSUFFICIENT`.
- **종합 인상 심사 (Track B)**: 조각은 합법이나 전체 인상에서 드러나는 오인위험을
  혜택 주장 ← 완화/강화 관계 그래프로 종합 판정.
- **일관 교정본·수정안**: 개별 지적을 모아 광고 전체를 일관 재작성, 원문↔교정본
  diff. 제안과 심사자 조언 분리, 할루시네이션 차단.
- **운영 대시보드·감사 추적**: 실행 스냅샷 저장·집계, 행 클릭 시 그 실행을 콘솔에서
  시점 재현.
- **로컬/클라우드 LLM 토글**: 클라우드(OpenAI)와 로컬 Ollama 모델을 요청별 라우팅.

### 본선 신규 (상세 변경이력: [docs/CHANGELOG_FEATURES.md](docs/CHANGELOG_FEATURES.md))

- **멀티모달 이미지 광고 접수**: 배너·전단·카드뉴스 이미지(최대 5장)에서 문안·
  레이아웃 소견을 비전 추출, 여러 장을 한 광고로 통합 심사. 판정은 항상 텍스트
  근거로만 동작(그라운딩 규율 유지).
- **이미지 수정 가이드**: 완성 광고 재현이 아니라 원본 위에 위험 취소선·교체
  문안·고지 영역을 번호 콜아웃으로 표시하는 검수 마크업 생성 + 자연어 지시 반복
  개선. 이미지에 실제로 있는 문구의 수정만 표시(본문 전용 교정 자동 제외).
- **다국가(캄보디아 PPCBank) 확장**: 은행 선택으로 워크스페이스·관할 법령을
  라우팅하는 2-DB 아키텍처. 코드 수정 없이 데이터 교체만으로 캄보디아 법령 심사,
  영어 우선 산출(원문 무번역·영어 판정문), 한국법 미주입 게이트.
- **심사 코파일럿 (CopilotKit×LangGraph)**: 심사 결과 위에서 자연어로 되묻는
  대화형 보조. 화면 컨텍스트 → 부족하면 Neo4j 정책·상품 그래프를 읽기 전용
  거버넌스 레이어(템플릿 우선+Text2Cypher 폴백)로 조회.
- **상품 문서 시점 인식 접수**: 상품설명서·약관의 시행일을 원문에서 인식(추정
  금지)해 KG에 버전 적재(`SUPERSEDES` 체인), 직전 버전 대비 조건 변경 자동 비교.
- **근거 경로 계층형 재설계**: Context Graph → CU 브랜치(fan-out) → 법령
  위임사슬 → 판정의 계층형 DAG. CU별 대표 근거 경로 + 연결 근거 전체 공개.
- **운영 대시보드 평가 로그 탭**: 합성 gold셋 정밀도·재현율 리포트(GOLD)와 실광고
  라이브 판정 로그(LIVE) 구분 표시, 유형·상품군·조문별 분해.
- **판정 모델 Provider 확장**: OpenAI 외 Anthropic Claude(strict tool-use로 정책
  어휘 enum을 문법 수준 강제, 스트리밍으로 대형 판정 안정화).
- **표현·브랜드세이프티 게이트 (Track C)**: 판례 코퍼스 기반 6축 표현 리스크
  게이트(워크스페이스별 온오프).

---

## 3. 파일 구조 (주요 기능별 모듈)

```text
graph-compliance-ccg/
├── server.py                  # FastAPI 진입점 — /api/review(+stream), 이미지 접수/수정가이드,
│                              #   상품문서 접수, 평가 리포트, 실행 기록 API
├── workflow.py                # 심사 파이프라인 오케스트레이션 (추출→정규화→검색→판정→교정)
│
│  # ── 추출·컨텍스트 그래프 ──
├── context_extractor.py       # 계층형 컨텍스트 추출 (ContextFrame→SentenceUnit→Claim→Qualifier)
├── normalizer.py              # ContextAnchor 정규화 (판정 단위)
├── claim_modeling.py          # 금소법 행위요건 feature layer
│
│  # ── 정책 그래프·검색 ──
├── policy_compiler.py         # 법령·심의기준 → CU/Premise/PolicyHypernym 컴파일 (1회성 적재)
├── vocabulary_governance.py   # PolicyHypernym 표준어휘 거버넌스
├── retriever.py               # Neo4j CU 후보 검색 (임베딩+법적요건 게이팅)
├── legal_elements.py          # CULegalElementProfile — CU별 성립 요건
├── planner.py                 # CUPlan 구성 (anchor↔CU 매칭·rerank)
├── policy_evidence.py         # 법령 위임사슬·고지·예외 근거 체인
│
│  # ── 판정 ──
├── judge.py                   # Track A: CU별 LLM 판정 (정의→요건→결론→유보)
├── overall_impression.py      # Track B: 전체 인상 종합 심사
├── rule_judgment.py           # 규칙 트랙 (escalate-only)
├── router.py                  # 최종 verdict 라우팅 (승인/검토/수정/반려)
├── risk_context.py            # Track C: 표현·브랜드세이프티 게이트
│
│  # ── 상품 사실 대조·고지 ──
├── product_facts.py           # ProductFact 추출·ClaimFact 비교·필수 고지 점검
├── disclosure_catalog.py      # 상품군별 필수 고지 카탈로그 (그래프 disc_*)
├── prominence.py              # 현저성(표시 위계) 진단
├── product_doc_intake.py      # [본선] 상품문서 시점 인식 접수 (버전 KG + 변경 추적)
│
│  # ── 멀티모달·수정안 ──
├── ad_image.py                # [본선] 이미지 광고 비전 추출 (1~5장) + 이미지 수정 가이드 생성
├── revision.py                # 일관 교정본·수정안 생성
├── ad_translation.py          # [본선] 참고용 번역 (KH: 영어 메인·크메르어 서브)
│
│  # ── 코파일럿·LLM 게이트웨이 ──
├── copilot_agent.py           # [본선] LangGraph 심사 코파일럿 (AG-UI)
├── copilot_graph_tools.py     # 읽기 전용 그래프 조회 도구 (템플릿+Text2Cypher, 거버넌스)
├── llm_gateway.py             # OpenAI/Anthropic/로컬 3-route 구조화 출력 게이트웨이
│
│  # ── 다국가 확장 ──
├── ingest_cambodia.py         # [본선] 캄보디아 법령 적재 (KH-CU, 소비자보호법 2019 등)
├── ingest_cambodia_products.py, build_ppcbank_product_graph.py
│
│  # ── 평가 ──
├── evaluate.py                # article-level multi-label 평가 하네스 (F1/F2/MCC + CCG 진단)
├── eval/                      # gold 데이터셋(JSONL)·합성 v0.2·평가 리포트·DATASET_CARD.md
│
├── frontend/                  # Next.js 심사 콘솔 (3-pane, 근거 그래프, 대시보드, 코파일럿)
│   └── src/components/console # ReviewConsole/RevisionDiff/GraphView/ExceptionView 등
├── tests/                     # pytest — 워크플로·서버·평가·이미지 회귀 테스트
├── data/                      # 캄보디아 법령 원문, 데모 상품문서 번들
└── docs/                      # 추론 아키텍처·기능 변경이력·기능명세서(docx)·데모 가이드
```

추론 아키텍처(결정론/해석 레인이 데이터→과정→결과를 나누는 방식, 다이어그램 포함):
[docs/REASONING_ARCHITECTURE.md](docs/REASONING_ARCHITECTURE.md)

---

## 4. 사용 데이터 및 외부 API

### 데이터

| 데이터 | 용도 | 위치/비고 |
|---|---|---|
| JB금융그룹 해커톤 데이터셋 (상품공시 PDF 6,098건 + 메타데이터 CSV) | 상품 사실 대조·필수 고지 교차확인 | 로컬 경로를 `JB_PRODUCT_DISCLOSURE_ROOT`/`JB_PRODUCT_METADATA_PATH`로 지정. 데모용 최소 번들은 `data/demo_product_documents/` 동봉 |
| 금융소비자보호법·시행령·감독규정, 금융광고 심의기준 | 정책 그래프(CU) 컴파일 원천 | Neo4j 워크스페이스 `graphcompliance_mvp_jb_20260530` |
| 금융위·금감원 금융광고규제 가이드라인 지적사례 | 판정 few-shot 근거(`eval/regulator_grounding.jsonl`) | 위반 패턴 카탈로그 v0.2의 원천 |
| 캄보디아 소비자보호법(2019)·Sub-Decree 232·Prakas 249 | [본선] KH 워크스페이스 정책 그래프 | `data/cambodia/` (원문 PDF+조문 JSON, 출처·회수 여부 기록) |
| 합성 gold 평가셋 v0.2 (34건, 10개 상품군) | 정밀도·재현율 평가 | `eval/synth_v0_2_*.jsonl` + `eval/DATASET_CARD.md` |
| UnSmile 등 혐오표현 판례 코퍼스 | Track C 표현 리스크 축 | 로컬 DB 전용 조회 |

골드 라벨은 평가 전용이며 추출·검색·판정·교정 프롬프트에 주입되지 않는다.

### 외부 API

| API | 용도 | 설정 |
|---|---|---|
| OpenAI Responses/Chat (`gpt-5.4-nano` 기본) | 추출·판정·교정 구조화 출력, 임베딩(`text-embedding-3-small`) | `OPENAI_API_KEY` |
| Anthropic Claude (Sonnet 5 등, 선택) | 판정 모델 대안 — strict tool-use(enum 문법 강제)+스트리밍 | `ANTHROPIC_API_KEY` |
| OpenAI 이미지 (`gpt-image-2` edit) | [본선] 이미지 수정 가이드 마크업 생성 | `CCG_IMAGE_MODEL`/`CCG_IMAGE_QUALITY` |
| Neo4j (Aura) | 정책·상품·컨텍스트 그래프 저장소 (KR/KH 2-DB) | `NEO4J_URI` 계열, KH는 `NEO4J_URI_CAMBODIA` 계열 |
| 로컬 Ollama (선택) | 로컬 LLM 라우팅 (json_schema 강제) | `LOCAL_LLM_BASE_URL` |

---

## 5. 재현성 · 평가

### 평가 하네스

GraphCompliance 논문의 article-level multi-label 프레임을 따른다.

```bash
# 저장된 예측 채점
python3 evaluate.py --input eval/smoke_financial_ad_review.jsonl --predictions output/ccg_predictions.jsonl

# 라이브 심사 + 채점 일괄
python3 evaluate.py --input eval/synth_v0_2_all.jsonl --run-live --output output/ccg_eval_report.json
```

지표: `micro/macro F1·F2`, `MCC` + CCG 진단(`cuplan_recall`,
`evidence_grounding_rate`, `overblocking_rate`, `exception_sanity_rate` 등).
평가 리포트는 콘솔 **운영 대시보드 → 평가 로그** 탭에서도 열람된다
(GOLD/LIVE 구분, 조문별 분해).

### 테스트

```bash
python3 -m pytest tests/ -q
```

### 주의 (알려진 한계)

- 합성 v0.2 평가를 `--workers 4` 이상으로 돌리면 Neo4j Aura 연결 리셋이
  재시도 없이 실패로 잡혀 지표가 오염될 수 있다 — `--workers 1~2` 권장
  (커밋 `a1cd541` 메시지에 기록).
- KH 워크스페이스의 CU 제목·조문 요약은 정책 컴파일러의 한국어 라벨 강제로
  한국어로 적재되어 있다. 심사 산출물(인용·판정·기준)은 영어로 나가지만,
  그래프 데이터 자체의 영어화는 재컴파일이 필요한 후속 작업.

---

## 6. 아키텍처 노트 (요약)

### Hierarchical Context Graph

```text
AdDraft -> ContextFrame -> SentenceUnit -> Claim -> ClaimQualifier/ClaimFact
        -> ConsumerEffect -> CUPlanItem/ProductFactComparison -> LLMJudgment
```

전체 광고를 먼저 읽어 인상 프레임을 만들고, 문장 단위로 분해해 문장 간
강화/완화 관계를 기록한 뒤 claim 세부를 추출한다. `누구나` 같은 표현이 독립
anchor가 아니라 부모 claim(`누구나 연 5% 확정 보장`)의 qualifier로 평가되는
이유다. 판정 evidence window에는 anchor별 ContextFrame·SentenceUnit·관계가
격리되어 들어간다(교차 오염 차단).

### Product Fact Graph (온디맨드)

```text
Claim -> ClaimFact -> Product -> ProductDocument -> ProductFact -> ComparisonResult
```

6,098건을 사전 추출하지 않는다. 심사 대상 상품을 해석해 그 상품의 PDF만 읽고,
추출 사실을 `review_run_id` 하위에 저장한다. `SUPPORTED`여도 조건·기간·세전세후
·예금자보호가 낮은 위계에 묻혀 있으면 Disclosure Gate가
`CONDITION_MISSING`/`PROMINENCE_INSUFFICIENT`를 띄운다.

### 온톨로지

`financial-compliance-ad-review.yaml`은 엔티티·관계·시각화·읽기 전용 에이전트
도구 shape의 수동 계약이다. 개별 정책 용어는 YAML enum이 아니라 정책 컴파일러가
생성하는 Neo4j `PolicyHypernym` 노드로 거버넌스된다.
