# JB Compliance · CONTENT SAFEGUARD — 코드 분석 보고서

> 분석 일자: 2026-06-30 · **읽기 전용 정적 분석**(코드 미수정, 라이브 Neo4j 미조회). 대상 저장소: `junbub/repo` (FastAPI 백엔드 + Neo4j + Next.js 콘솔 + OpenAI/Ollama 토글).
> 인용은 `파일:라인`/`함수()` 기준. 자동 검증에서 38개 표본 인용이 ±5줄 내 일치(불일치 0건). 추정은 `불확실:`로 명시.


## 목차

- 1. 저장소 구조 & 진입점
- 1-FE. 프론트엔드 아키텍처
- 2. 전체 데이터 플로우
- 2-검색. CU 게이팅/검색 단계 (데이터플로우 관점)
- 2-판정. 판정 · 수정안 상세
- 3. Neo4j 스키마 (코드 실측)
- 4. 법령 적재(ingestion) 파이프라인
- 5. ★ PolicyHypernym 어휘 (언어중립 ID인가 한국어 문자열인가)
- 6. Claim 추출/정규화
- 7. 검색/게이팅 메커니즘
- 8. 관할/멀티-룰셋 개념 존재 여부
- 9. DisclosureRequirement(필수 고지) 카탈로그
- 10. 로컬/클라우드 LLM 토글 & json_schema 강제
- 11. Eval 하니스
- 12. 환경변수 & 비밀정보 점검
- 캄보디아 확장 지점 (KH Jurisdiction Expansion)


---

## 1. 저장소 구조 & 진입점

### 디렉터리 트리(루트 백엔드 모듈을 역할별로 묶음)

루트 절대경로: `/Users/kunwoo/Desktop/workspace/junbub/repo`. 백엔드는 루트에 평면 배치된 40개 `.py`(루트 `find` 결과 기준).

```
repo/
├─ [진입점/오케스트레이션]
│  ├─ server.py            FastAPI app + 라우트 + 정적 마운트(아래 §진입점)
│  ├─ review_ad.py         LLM-only 리뷰어 CLI (argparse)
│  ├─ workflow.py          GraphComplianceCCGWorkflow.review/review_events 본체(31KB)
│  ├─ planner.py           리뷰 단계 계획
│  └─ router.py            단계/경로 라우팅(24KB)
├─ [스키마·영속]
│  ├─ schemas.py           pydantic 모델(ReviewInput/Output 등)
│  ├─ persistence.py       Neo4j 드라이버/세션(39KB)
│  ├─ run_store.py         실행 스냅샷 저장/조회(파일+Neo4j) record_run/list_runs/load_run
│  └─ jb_data_context.py   JB 데이터/Neo4j 컨텍스트, search_products
├─ [적재(ingest)]
│  ├─ load_product_graph.py        Product 그래프 적재
│  ├─ build_cross_law_citations.py 교차 법령 인용 구축
│  ├─ build_synthetic_eval_dataset.py 합성 eval 데이터셋 생성(37KB)
│  ├─ policy_compiler.py           정책 컴파일(Premise 임베딩 등, 37KB)
│  └─ vocabulary_governance.py     PolicyHypernym 어휘 거버넌스
├─ [검색·게이팅(retrieval/gating)]
│  ├─ retriever.py                 검색(27KB)
│  ├─ retrieval_probe.py           검색 프로브
│  ├─ ccg_embeddings.py            임베딩 클라이언트
│  ├─ cross_encoder_reranker.py    선택적 cross-encoder 재랭크
│  ├─ applicability_gate.py        적용성 게이트
│  └─ bridge_exception_rules.py    예외 규칙 브리지(Neo4j)
├─ [판정(judgment)]
│  ├─ judge.py                     LLM 판정(24KB)
│  ├─ rule_judgment.py             규칙 기반 판정
│  ├─ legal_elements.py / legal_hierarchy.py  법적 요건/위계
│  ├─ claim_modeling.py / overall_impression.py / prominence.py  Claim/전체인상/현저성
│  ├─ disclosure_catalog.py        고지 카탈로그(Neo4j)
│  ├─ policy_evidence.py / risk_context.py / context_extractor.py(43KB)  정책근거/리스크/맥락 추출
│  ├─ normalizer.py                정책 정규화(PolicyHypernym id)
│  └─ revision.py                  수정안 생성(22KB)
├─ [LLM]
│  ├─ llm_gateway.py               LLMGateway: 클라우드(OpenAI Responses)↔로컬(Ollama/Chat) 토글
│  └─ product_facts.py             상품설명서 사실/PDF 경로 해석(36KB)
├─ [eval]
│  ├─ evaluate.py                  평가 실행(23KB)
│  └─ quality_report_synthetic_eval_dataset.py  품질 리포트
├─ [유틸/부트스트랩]
│  ├─ env_loader.py                .env 로더(load_local_env)
│  ├─ utils.py                     to_jsonable 등
│  └─ __init__.py                  패키지 docstring만(2줄)
├─ frontend/   Next.js 16 콘솔(아래 §프론트). src/app, src/components, src/lib, src/hooks, fixtures
├─ console/    레거시 정적 콘솔: index.html(5KB) + app.js(92KB) + styles.css + review_console_v2/v3.html
├─ eval/       데이터셋: redteam_korean_financial_ad_12.jsonl, smoke_..jsonl, synthetic_product_fact_100.jsonl, violation_taxonomy_v0_1.json, DATASET_CARD.md
├─ docs/       HANDOFF.md, REASONING_ARCHITECTURE.md, retrieval_architecture.html, copilotkit_integration_phase1.md, WORKLOG_2026-06-14.md
├─ data/       ontology.yaml (단일 파일)
├─ tests/      test_workflow.py(105KB), test_revision.py, test_product_facts.py
├─ financial-compliance-ad-review.yaml   파이프라인 정의(8KB, 루트)
├─ requirements.txt, README.md, RUN.md, .env(gitignore됨), .env.example, .gitignore, .claude/
```

### 진입점

**백엔드 app 객체**: `server.py:33` `app = FastAPI(title="GraphCompliance CCG", version="0.1.0")`. 부트스트랩은 `server.py:28` `load_local_env(Path.cwd() / ".env")`, 로깅 레벨은 `CCG_LOG_LEVEL`(`server.py:30`).

**등록 라우트**(`@app.get/@app.post` 전수):
- `GET /health` → `health()` `server.py:49-51`
- `GET /api/products/search` → `products_search(q, product_group, limit)` `server.py:54-58` (→ `search_products`)
- `POST /api/review` → `review(payload)` `server.py:61-65` (동기 1회 리뷰 + `record_run`)
- `POST /api/review/stream` → `review_stream(payload)` `server.py:116-117` (NDJSON 스트리밍, heartbeat = `CCG_REVIEW_STREAM_HEARTBEAT_SECONDS`)
- `GET /api/product-doc/{document_id}` → `product_doc(document_id)` `server.py:176-177` (상품설명서 PDF inline; path-traversal 방어 `server.py:197-204`)
- `GET /api/runs` → `runs(limit=100)` `server.py:214-215`
- `GET /api/runs/{run_id}` → `run_detail(run_id)` `server.py:220-221`
- `GET /` → `console()` `server.py:229-231` (`console/index.html` 반환)

**정적 마운트**: `server.py:234` `app.mount("/console", StaticFiles(directory=CONSOLE_DIR), name="console")`. `CONSOLE_DIR = <repo>/console` (`server.py:34`). 즉 루트 `/`와 `/console/*`는 레거시 정적 콘솔(`console/index.html` + `console/app.js`)을 서빙 — Next.js 프론트(`frontend/`)와는 별개 UI.

**프론트 app(Next.js 16, App Router)**: 루트 레이아웃 `frontend/src/app/layout.tsx`(`metadata.title = "JB Compliance · CONTENT SAFEGUARD"`, `layout.tsx:16`), 페이지 `frontend/src/app/page.tsx`(`export default function Page()` `page.tsx:33`, `"use client"` `page.tsx:1`). 서버 라우트 핸들러 2개:
- `frontend/src/app/api/review/stream/route.ts` — FastAPI `${CCG_API_BASE}/api/review/stream`로 NDJSON 패스스루(`route.ts:14-21`)
- `frontend/src/app/api/chat/route.ts` — Mac mini LLM(`LLM_BASE_URL`)으로 서버사이드 프록시(`route.ts:19-44`)

**실행 스크립트**:
- 백엔드: repo 루트에서 `uvicorn server:app --port 8770` (이미 확인된 사실 (c); `server.py:33`의 `app`가 ASGI 대상). RUN.md에 기동 절차 기재.
- 프론트 dev: `frontend/package.json:6` `"dev": "next dev"` → `npm run dev`; build/start/lint도 동일 파일 `scripts`.
- CLI: `review_ad.py` — `python review_ad.py` (`if __name__ == "__main__": raise SystemExit(main())` `review_ad.py:48-49`). argparse 인자: `--text`, `--input-json`, `--dataset-item-id`, `--title`, `--channel`(기본 `bank_event_page_text`), `--source-type`, `--product-group`(기본 `auto`), `--workspace-id`(기본 `graphcompliance_mvp_jb_20260530`), `--output` (`review_ad.py:15-23`). `GraphComplianceCCGWorkflow().review(...)` 직접 호출(`review_ad.py:39`).
- 프론트 rewrite: `frontend/next.config.ts:6-10`가 `/api/:path*`·`/health`를 `CCG_API_BASE`(기본 `http://localhost:8770`)로 프록시(`next.config.ts:3`).

**`.claude/launch.json` 의 의미**: `version 0.0.1`, 단일 configuration `"ccg-frontend"`. `runtimeExecutable: npm`, `runtimeArgs: ["run","dev","--prefix","frontend","--","--port","3100"]`, `port: 3100`. 즉 이 런처는 **Next.js 프론트 dev 서버를 3100 포트로** 기동하는 IDE/툴 실행 정의일 뿐, 백엔드(8770)나 정적 console과는 무관. (불확실: 어떤 도구가 이 `launch.json`을 소비하는지는 파일만으로 단정 불가 — VS Code 표준 `.vscode/launch.json`이 아니라 `.claude/` 하위라는 점만 확인됨.)

---

## 1-FE. 프론트엔드 아키텍처

### 라우팅 / 렌더 구조
- SPA 단일 페이지 + 클라이언트 사이드 탭 전환 방식이다. 라우트는 `app/layout.tsx`(루트 레이아웃, `lang="ko"`, Pretendard CDN, 메타데이터 "JB Compliance · CONTENT SAFEGUARD" — `app/layout.tsx:15-19`, `:27-34`)와 `app/page.tsx`(`"use client"`)뿐이다. 별도 Next 라우트 세그먼트로 탭을 나누지 않고, `app/page.tsx:35`의 `useState<ViewKey>("home")` 단일 상태로 패널을 분기 렌더한다.
- `ViewKey`는 `home | new | review | revision | graph | exception | product | audit | dashboard`(`components/shell/Sidebar.tsx:7`). 좌측 `Sidebar`가 `setView`로 전환하고(`app/page.tsx:165`), 본문은 `view === ...` 조건부 렌더로 구성된다: `home`→`HomeTab`(`:176-187`), `new`→`ReviewForm`+우측 실시간 진행 `AuditTab`(`:189-262`), `review`→3-페인 콘솔 `AdPane`/`RiskList`/`DetailPane`(`:264-304`), `graph`→`GraphView`(`:306-310`), `exception`→`ExceptionView`(`:312-316`), `product`→`ProductFactsTab`(`:318-322`), `revision`→`RevisionTab`(`:324-331`), `dashboard`→`DashboardTab`+펼침형 `AuditTab`/`OverallTab`/`SentenceMapTab`(`:333-366`). 참고: `audit` ViewKey는 `NAV` 배열(`Sidebar.tsx:9-18`)에 항목이 없어 사이드바로는 진입 불가 — 감사 로그는 `new`/`dashboard` 안에 `AuditTab`으로 내장됨(`page.tsx:250`, `:346`).
- 상단 `ContextBar`는 view와 무관하게 항상 렌더되며 `state.status`, `result`, `meta.title`, `state.events`, `decision`을 받아 AI 판정 배지·오인 위험 등급·심사자 결정 버튼을 표시한다(`app/page.tsx:167-174`, `components/shell/ContextBar.tsx:16`).

### 상태 관리 — `useReview` 훅
- 핵심 상태는 `hooks/useReview.ts`의 `useReducer`(`ReviewState`: `status/result/reviewedText/events/error/selectedAnchorId/selectedPrinciple` — `useReview.ts:9-18`, `:96-97`)에 집중된다. `runReview(payload)`가 스트리밍 실행을 구동하고(`:101`), `selectAnchor`/`togglePrinciple`/`loadSample` 액션을 노출한다(`:231-241`).
- `runReview`는 `AbortController`로 이전 실행을 취소(`:102-104`)하고, 두 종류 워치독(soft warning `STREAM_STALL_WARNING_MS` 기본 300초 / hard abort `STREAM_HARD_ABORT_MS` 기본 1200초 — `:33-34`, `:115-140`)과 `/health` 폴링(15초 주기, 연속 2회 실패 시 `backend_unreachable`로 fail-fast — `:36`, `:149-169`, `:195-203`)을 건다.
- `result` 확정 시 `reviewedText`를 `normalize("NFC")`로 정규화한다(`:69`, `:88`) — 하이라이트 span 정렬을 위한 NFC/NFD 불일치 방지.
- `app/page.tsx`는 `useReview`를 호출(`:34`)하고, 그 외 UI 전용 로컬 상태(`view/meta/resolved/acknowledged/decision/toast/draftPreset`)를 별도 `useState`로 보유(`:35-42`). `resolved`(수정안 적용)와 `acknowledged`(심사자 확인)는 의미가 달라 분리됨(`:38-39`).

### 백엔드 호출 경로
- 리뷰 실행: `ReviewForm` → `onSubmit`(`page.tsx:44 handleSubmit`) → `runReview`(`useReview.ts:101`) → `streamReview`(`lib/api.ts:45`)가 **`POST /api/review/stream`**(NDJSON)을 호출하고 줄 단위로 파싱하여 `onEvent` 콜백으로 흘린다(`api.ts:50-86`). `event.event === "error"`면 `streamErrorToApiError`로 throw(`api.ts:71-73`, `:32-39`).
- `/api/review/stream`은 Next 라우트 핸들러 `app/api/review/stream/route.ts`가 **명시적으로 프록시/파이프**한다: `fetch(${API_BASE}/api/review/stream)`(`API_BASE = CCG_API_BASE ?? http://localhost:8770`, `:3`), `duplex:"half"`, 응답 본문을 그대로 스트리밍하며 `Content-Type: application/x-ndjson`, `X-Accel-Buffering: no`로 내보낸다(`:14-31`). 주석상 dev rewrite 프록시가 큰 청크를 버퍼링하는 문제를 우회하려는 목적(`:6-12`).
- 그 외 호출은 라우트 핸들러 없이 `next.config.ts`의 rewrite로 백엔드에 직접 전달된다(`/api/:path* → ${API_BASE}/api/:path*`, `/health → ${API_BASE}/health` — `next.config.ts:6-11`): `fetchRuns` `GET /api/runs`(`api.ts:89-94`), `fetchRun` `GET /api/runs/{id}`(`:97-101`), `searchProducts` `GET /api/products/search`(`:103-119`), `checkHealth`/health-probe `GET /health`(`api.ts:121-128`, `useReview.ts:154`), 그리고 상품문서 뷰어 `GET /api/product-doc/{id}`(`tabs/ProductFactsTab.tsx:29`).
- 별도 경로: `app/api/chat/route.ts`는 위 흐름과 분리된 LLM 직결 프록시다 — 브라우저에는 `LLM_BASE_URL`/`LLM_API_KEY`를 노출하지 않고 서버에서 `POST {LLM_BASE_URL}/v1/chat/completions`(기본 모델 `ax-4.0-light`)로 중계하며 SSE를 언버퍼링 통과(`route.ts:17-58`). 불확실: 현재 `src` 내에서 `/api/chat`을 호출하는 코드는 확인되지 않음(리뷰 워크플로우와 무관한 보조/미사용 엔드포인트로 보임).

### 리뷰 요청 폼 (`ReviewForm.tsx`) — 입력 필드와 제출 흐름
- 입력 상태(모두 `useState`, `draftPreset`로 초기화 — `ReviewForm.tsx:36-46`): `title`, `productGroup`, `channel`, `selectedProduct`/`productQuery`(상품 DB 검색·선택), `text`(광고 문안), `llmModel`(판정 모델), 그리고 큐(`draftQueue`).
- 화면 필드: 샘플 프리셋 버튼(`:150-175`), 심사 제목(`:177-188`), 상품군 `<select>`(`PRODUCT_GROUPS` — `:191-209`), 채널 `<select>`(`CHANNELS` — `:210-219`), 상품명 검색 콤보박스(`searchProducts` 디바운스 220ms — `:60-79`, `:220-286`), 채널 형식 요건 안내(`CHANNEL_FORMAT_HINT[channel]` — `:21-27`, `:289-295`), 광고 문안 `<textarea>`(required — `:297-310`), 판정 모델 `<select>`(`LLM_MODELS` — `:356-369`).
- `buildPayload()`가 `ReviewRequest`를 조립한다(`:93-103`): `dataset_item_id`(`console_${Date.now()}`), `title`, `content_text`, `channel`, `product_group`, `selected_product_name`(trim), `workspace_id`(`WORKSPACE_ID` 상수 — `labels.ts:3`), `llm_model`(빈 값이면 `undefined`), `actor`(`getActor()` localStorage 가명 — `lib/actor.ts:25`).
- 제출 흐름: `handleSubmit`(`:105-109`)가 `preventDefault` 후 `text` 비었거나 실행 중이면 차단하고 `onSubmit(buildPayload())` 호출 → `page.tsx handleSubmit`(`:44`) → `runReview` → 성공 시 `setView("review")`(`:54`). 큐 실행 `runQueue`는 `{ stayOnNew: true }`로 화면을 `new`에 유지하며 순차 실행(`:120-139`, `page.tsx:54`).
- `ReviewRequest` 타입 정의: `lib/types.ts:619-632`. `channel`/`product_group`은 `string`, `source_type?`는 옵셔널이나 `buildPayload`에서는 설정하지 않음(현재 `ReviewForm`은 `source_type`을 보내지 않으며, `page.tsx`의 `handleEditRun`만 `run.source_type`을 프리셋에 채움 — `page.tsx:120`).

### 탭 구성과 데이터 출처(selectors)
- Dashboard(`DashboardTab.tsx`): `fetchRuns()` → `GET /api/runs`(`:97-122`)로 받은 `RunSummary[]`만 사용. 집계(반려율/통과율/평균 위험/원칙·고지·CU 빈도)는 `seed` 제외 실제 실행 기준으로 클라이언트 계산(`:127-175`). `result`(현재 ReviewOutput)와 무관 — 별도 백엔드 데이터.
- Overall(`OverallTab.tsx`): `result.context_frame`와 `result.context_influences`(`:15-16`). selectors 미사용, `result` 직접 접근.
- ProductFacts(`ProductFactsTab.tsx`): `result.product_fact_context`(claim_facts / product_facts / comparison_results / selected_documents) — selectors `claimFactById`, `productFactById` 사용(`:4`). 상품문서 뷰어는 `GET /api/product-doc/{id}`(`:29`).
- Revision(`RevisionTab.tsx`): selectors의 교정 모델 전반 — `buildIssueCards`, `revisionFor`, `buildCorrectedCopy`/`buildBeforeDiff`/`buildDocumentDiff`, `correctedDocument`, `correctedDisclosureBlock`, `requiredDisclosureSlots`(`:4-19`). `resolved` 집합과 `state.reviewedText`로 Before/After diff 생성(`page.tsx:324-331`).
- SentenceMap(`SentenceMapTab.tsx`): `result.sentence_units`, `result.inter_sentence_relations`(`:17-18`), selectors `claimsForSentence`/`anchorForClaim`/`sentenceById`(`:4`). 앵커 선택 시 `onSelectAnchor`로 `review` 콘솔로 점프(`page.tsx:352-357`).
- Audit(`AuditTab.tsx`): `state.events`(스트림 이벤트)와 `result.policy_evidence_chains`/`context_anchors`/`cu_plan`/`system_review_items`로 단계 추적 합성(`buildAuditSteps` — `:25-50`).
- 심사 콘솔(`review`)과 사이드바 카운트는 `lib/selectors.ts`의 `buildIssueCards`(`:1065`)·`disclosureIsSatisfied`·`highlightCandidates`/`annotateText`/`buildAdLines` 등 순수 read-model 헬퍼에 의존(`Sidebar.tsx:28-31`, `selectors.ts:392-676`, `:1065-1183`).

### [seam] 관할(KH/KR) 토글 삽입 지점
현재 코드베이스에 jurisdiction/region/locale 개념은 **전무**하다(grep 결과: `frontend/src` 내 `jurisdiction|관할|cambodia|캄보디아|KH|region|locale` 일치 없음 — 시간 포맷 `ko-KR` 문자열만 검출). 따라서 끝-단부터 정확히 다음 지점에 끼우면 된다.

1. 라벨/옵션 상수 추가 — `lib/labels.ts`. `CHANNELS`(`:258-265`)·`PRODUCT_GROUPS`(`:250-256`) 옆에 `JURISDICTIONS = [{ value: "KR", label: "한국" }, { value: "KH", label: "캄보디아" }] as const` 신설. (캄보디아 채널/상품군/고지 카탈로그가 한국과 다르면 여기서 관할별로 분기.)

2. 요청 타입 필드 — `lib/types.ts`의 `ReviewRequest`(`:619-632`)에 `jurisdiction?: string;`(예: `"KR" | "KH"`) 추가. 백엔드가 이 필드로 법령·심의기준 코퍼스를 선택하도록 계약 확장. 동시에 `RunSummary`(`types.ts:286-310`)에도 `jurisdiction?` 추가하면 대시보드/재실행에서 보존된다.

3. 폼 입력 + payload — `components/ReviewForm.tsx`:
   - 상태: `const [jurisdiction, setJurisdiction] = useState(draftPreset?.jurisdiction ?? "KR")` — 기존 `useState` 블록(`:36-46`)에 추가.
   - 입력 UI: 상품군/채널 `<select>` 그리드(`:190-219`) 안에 동일 패턴의 관할 `<select>` 추가(`JURISDICTIONS` 매핑).
   - payload: `buildPayload()`(`:93-103`) 객체에 `jurisdiction` 한 줄 추가. 큐 항목(`addToQueue` `:111-114`, `runQueue` `:127-134`)은 `...buildPayload()`/`...item`을 전개하므로 자동 포함됨.
   - 프리셋 채움: `fillExample`(`:50-58`)은 `ExamplePreset`에 관할 필드를 더하면 함께 채워짐(`labels.ts:267-301`). `draftPreset` 경유 재실행은 (2)에서 타입만 맞추면 동작.

4. 상위 프리셋 전파 — `app/page.tsx`: `handleEditRun`(`:112-127`)이 `RunSummary` → `draftPreset`로 옮길 때 `jurisdiction: run.jurisdiction`를 추가해야 재실행 시 관할이 보존된다. `handleUsePreset`(`:103-110`)은 `...preset` 전개라 자동.

5. 컨텍스트 바 표시 — `components/shell/ContextBar.tsx`: 현재 `ReviewMeta`(`page.tsx:28-31`)는 `title`/`channelLabel`만 보유. 관할 배지를 보이려면 (a) `page.tsx handleSubmit`(`:44-58`)·`handleOpenRun`(`:87-101`)에서 `setMeta`에 `jurisdictionLabel` 추가, (b) `ContextBar` props에 전달(`page.tsx:167-174`), (c) `ContextBar.tsx`의 제목 줄/`review_run_id` 영역(`:24-37`)에 배지 렌더. 단, `ContextBar`는 `result`를 받으므로 `RunSummary`/`ReviewOutput`에 관할이 실리면 `meta` 없이도 표시 가능.

6. (선택) 사이드바/대시보드 — 관할별 운영 지표를 보려면 `components/shell/Sidebar.tsx`의 현재 ReviewRun 카드(`:84-106`)나 `DashboardTab.tsx`의 `BarList`/집계(`:170-175`)에 `run.jurisdiction` 기반 필터·분포를 추가. 불확실: 백엔드 `/api/runs` 응답에 관할 필드가 실제로 포함되는지는 백엔드 스키마(`schemas.py`) 확인 필요 — 본 분석 범위(frontend) 밖.

핵심 seam은 **(2) `ReviewRequest.jurisdiction` 타입 + (3) `buildPayload` 한 줄**이며, 이 둘만으로 백엔드까지 관할 신호가 전달된다. 나머지(1·4·5·6)는 표시·보존·UX 일관성을 위한 보강이다.

---

## 2. 전체 데이터 플로우

메인 오케스트레이터는 `GraphComplianceCCGWorkflow`(workflow.py:33)이며, 진입점은 두 개다. 동기 단발 호출 `review()`(workflow.py:61)는 내부적으로 제너레이터 `review_events()`(workflow.py:70)를 끝까지 돌려 `event=="result"`만 추출해 `ReviewOutput`을 반환한다. 스트리밍은 `review_events()`가 단계별 NDJSON 이벤트를 직접 `yield`한다.

서버 연결 지점:
- 동기: server.py:61 `/api/review` → server.py:64 `workflow_for(payload)` → server.py:65 `workflow.review(review_input_from_payload(payload))`.
- 스트리밍: server.py:116 `/api/review/stream` → server.py:124~126 `workflow.review_events(review_input)` 루프, `event=="result"`이면 `record_run`으로 스냅샷 저장(server.py:132~145).
- `workflow_for()`(server.py:37)는 `payload.llm_model`이 있으면 `LLMGateway(model=...)`로 모델만 오버라이드(server.py:43~46). 클라우드↔로컬(Ollama) 토글은 `.env`의 `LLM_BASE_URL`이 결정(주석 server.py:40~42).
- `review_input_from_payload()`(workflow.py:510)는 `payload` dict를 `ReviewInput`으로 변환하며, `title`/`content_text`를 `unicodedata.normalize("NFC", ...)`로 정규화(workflow.py:516~517). 기본 `workspace_id`는 `"graphcompliance_mvp_jb_20260530"`(workflow.py:523).

`review_events()` 호출 순서(workflow.py:70~507):
1. ID 발급: `content_hash`, `ad_draft_id`(stable_id), `review_run_id`(stable_id + uuid4) — workflow.py:71~73. `start` 이벤트(:75).
2. Policy alignment check: `self.retriever.assert_policy_alignment_ready(...)` — :83.
3. Hierarchical context extraction: `self.extractor.extract_hierarchical(...)` → `extraction.claims`, 이어서 `build_context_triples(...)` — :92~101. (§6 상세)
4. Policy context retrieval: `self.retriever.policy_context_for_claims(... query_text=content_text[:1200], limit=80)` → hypernyms/premises/fragments — :125~129.
5. Policy normalization: `self.normalizer.normalize(...)` → anchors, 이어서 `fold_qualifier_anchors_into_parent_claims(...)`(:153), `attach_anchor_feature_sets(...)`(:154). (§6 상세)
6. Product disclosure context: `build_product_context(review_input, claims)` — :181.
7. Product fact graph: `self.product_facts.analyze(...)` — :198.
8. Prominence disclosure gate: `build_prominence_artifacts(...)` — :226.
9. Track B overall impression: `self.overall_impression.judge(...)` — :249.
10. CU candidate retrieval: anchor별 `self.retriever.candidates_for_anchor(... limit=12)` — :275~284. (§7 상세)
11. Cross-encoder CU rerank: `self.cross_encoder_reranker.rerank(... limit_per_anchor=8)` — :311. (§7 상세)
12. LLM CU rerank: `self.planner.plan(...)` → `cu_plan`, 이어 `build_retrieval_diagnostics(...)`(:351), `summarize_cu_gate(...)`(:358). (§7 상세)
13. Policy evidence chains: `build_policy_evidence_chains(...)` — :383.
14. Evidence window build: `self.judge.build_evidence_windows(...)` — :408.
15. LLM judgment: `self.judge.judge(...)` → `judgments` — :422.
16. Exception override: `NON_COMPLIANT`이고 `legal_element_profile.exception_eligible`인 건만 `self.retriever.exception_closure(...)` + `exception_closure_has_mitigation_evidence(...)` 후 `self.judge.review_exception(...)` — :442~464.
17. ReviewGraph 조립(:467) → Neo4j 영속화 `self.writer.save(...)`(:497).
18. Revision suggestions: `self.revision.suggest(...)` — :501.
19. Routing: `build_output(review_input, graph, revision_suggestions=...)` — :505. (router.py)
20. `result` 이벤트로 `output` 반환 — :507.

단계 매핑 표:

| 단계 | 담당 파일:함수() | 입력 → 출력 |
|---|---|---|
| 입력 변환 | workflow.py:510 `review_input_from_payload()` | payload dict → `ReviewInput`(NFC 정규화) |
| 맥락/구조 분석 | context_extractor.py:290 `LLMContextExtractor.extract_hierarchical()` | `ReviewInput` → `ContextFrame`+`SentenceUnit[]`+`InterSentenceRelation[]`+`ContextInfluence[]`+`Claim[]` |
| Claim 추출 | context_extractor.py:567~619 `_build_extraction_from_result()` | LLM JSON → `Claim`/`ClaimQualifier`/`ContextEntity`(claim_id 부여) |
| Claim 정규화 | normalizer.py:66 `PolicyGuidedNormalizer.normalize()` | `claims`+`policy_context` → `ContextAnchor[]`(PolicyHypernym 매핑) |
| Qualifier 폴딩 | claim_modeling.py:23 `fold_qualifier_anchors_into_parent_claims()` | anchors+claims → 정제된 anchors |
| CU 게이팅/검색 | retriever `candidates_for_anchor()` / planner.py:46 `plan()` | anchors → `candidates_by_anchor` → `CUPlanItem[]` (§7) |
| 판정(Track A) | judge `judge()` (workflow.py:422) | plan+evidence_windows → `LLMJudgment[]` (판정 §) |
| 판정(Track B) | overall_impression.py `judge()` (workflow.py:249) | claims+증거 → 전체 인상 판정 dict |
| 예외 override | judge `review_exception()` (workflow.py:459) | NON_COMPLIANT 판정 → `ExceptionReview[]` |
| 결과/라우팅 | router.py:14 `build_output()` | `ReviewGraph` → `ReviewOutput`(final_verdict, detected_issues 등) |
| 수정안 | revision `suggest()` (workflow.py:501) | graph → `revision_suggestions` |
| 영속화 | persistence `Neo4jReviewWriter.save()` (workflow.py:497) | `ReviewInput`+`ReviewGraph` → Neo4j |
| 대시보드 | server.py:66 `to_jsonable(output)` + `record_run(...)` | `ReviewOutput` → JSON 스냅샷 |

`build_output()`의 최종 판정 로직(router.py:35~48): NON_COMPLIANT 중 `score>=0.82`이면 `reject`, NON_COMPLIANT 있으면 `revise`, Track B `verdict=="HIGH"` 또는 `misleading_score>=0.75`이면 `revise`, INSUFFICIENT/중위험/미매칭 actionable이 있으면 `needs_review`, 그 외 `pass_candidate`. Track C는 현재 비활성(stub)으로 `track_c_extension_summary()`가 정적 dict만 반환(risk_context.py:48~56, `status="extension_ready"`).

---

## 2-검색. CU 게이팅/검색 단계 (데이터플로우 관점)

파이프라인 순서는 `workflow.py`에서 다음과 같이 직렬로 실행된다(모두 `candidates_by_anchor`를 단계적으로 좁힘).

1. **CU 후보검색 (CU candidate retrieval)** — `workflow.py:274-284`. 앵커별로 `self.retriever.candidates_for_anchor(... limit=12)` 호출. 핵심 검색은 `Neo4jPolicyRetriever.candidates_for_anchor()`(`retriever.py:149-287`).
   - 진입 조건: 앵커에 `hypernym_ids`가 하나도 없으면 즉시 `return []` (`retriever.py:159-160`). 즉 정규화 LLM이 PolicyHypernym을 못 붙이면 임베딩이 아무리 가까워도 후보 0건 (`retrieval_probe.py:259-268`이 이 "리콜 구멍"을 실증).
   - DB 단계에서 어휘 overlap + 벡터 유사도가 **혼합**으로 후보를 거른 뒤(아래 §7 참조), Python 단계 게이트가 순차 적용됨: `with_scope_gate` -> `with_legal_element_gate` -> `candidate_allowed_for_anchor` 필터 -> `combined_score` 내림차순 정렬 후 `[:limit]` (`retriever.py:280-287`).

2. **Cross-encoder CU rerank** — `workflow.py:304-341`. `self.cross_encoder_reranker.rerank(... limit_per_anchor=8)` (`workflow.py:311-315`). 기본은 비활성(`NoopCUReranker`는 후보를 그대로 반환, `cross_encoder_reranker.py:43-50`). LLM rerank **앞**에 위치.

3. **LLM CU rerank -> CUPlan 구성** — `workflow.py:343-350`. `LLMCUPlanner.plan(... per_anchor_limit=5, total_limit=20)` (`planner.py:46-132`). LLM은 앵커당 상위 `RERANK_CANDIDATES_PER_ANCHOR=8`개만 본다(`planner.py:13, 57`).

4. **게이트 요약/진단** — `summarize_cu_gate`(`applicability_gate.py:117-161`)가 통과 CU(`enabled_cus`)와 탈락 CU(`skipped_cus`)를 집계. 탈락 진단(failure_code)은 `build_retrieval_diagnostics`(`workflow.py:541-575`)가 산출.

별도로 **공시/고지 요건 게이트**(상품군·채널 기준)는 CU 검색과 무관하게 `gate_disclosure_catalog`(`applicability_gate.py:64-104`)가 카탈로그 항목을 ON/OFF 처리한다.

---

## 2-판정. 판정 · 수정안 상세

### Track A(개별 CU) vs Track B(전체 인상)

두 트랙은 서로 다른 판단 단위·법리·산출 enum을 가진다.

**Track A — 개별 CU 단위 LLM 판정(`judge.py`).** `LLMComplianceJudge.judge()`(`judge.py:158`)가 `cu_plan`의 각 항목(`CUPlanItem`)을 독립 단위로 판정한다. 각 항목마다 `build_legal_test(item, anchor)`(`judge.py:360`)로 "규칙기반 판단 레이어"를 만들어 LLM에 함께 제시하고(`judge.py:188-190`의 `legal_test` 키), 한 번의 `self.llm.structured(...)` 호출(`judge.py:198`, name=`graphcompliance_cu_judgment`)로 모든 항목을 배치 판정한다. 산출 enum은 `COMPLIANT / NON_COMPLIANT / INSUFFICIENT / NOT_APPLICABLE`(`JUDGE_SCHEMA`, `judge.py:46`). 판단 단위는 "이 anchor/조문이 금지·요구하는 행위"이며, 시스템 프롬프트가 "각 항목은 독립된 ContextAnchor·EvidenceWindow·CUPlanItem이며 … 다른 항목의 광고 문구를 증거로 쓰지 마세요"로 격리를 강제한다(`judge.py:204-206`).

**Track B — 전체 인상 종합(`overall_impression.py`).** `LLMOverallImpressionJudge.judge()`(`overall_impression.py:41`)는 개별 CU가 아니라 광고 전체를 한 단위로 본다. 단일 LLM 호출(`overall_impression.py:69`, name=`graphcompliance_overall_impression`)로 "복잡 위반"(개별 문구는 모두 합법이나 흩어진 조각의 종합 인상이 오인)을 탐지한다. 산출 enum은 `LOW / MEDIUM / HIGH / INSUFFICIENT`(`OVERALL_IMPRESSION_SCHEMA`, `overall_impression.py:18`)로 Track A와 다르며, 위반 단정이 아니라 "라우팅용 오인위험"만 낸다(`overall_impression.py:85`). 적용 기준은 "대법원 2017두60109 전체적·궁극적 인상 기준"으로 산출에 명시(`overall_impression.py:110`). 종합 입력은 세 종류의 흩어진 증거다: `sentence_layers`(혜택·고지 문장의 role·prominence_tier, `overall_impression.py:54-58`), `prominence_gaps`(`PROMINENCE_INSUFFICIENT`/`DISCLOSURE_MISSING`만 필터, `overall_impression.py:59-63`), `fact_contradictions`(`CONTRADICTED`/`CONDITION_MISSING`/`NO_PRODUCT_FACT`, `overall_impression.py:64-68`). 점수는 verdict별 구간으로 보정한다(`calibrate_score()`, `overall_impression.py:156`: LOW≤0.35, MEDIUM 0.36~0.68, HIGH≥0.69).

**차이 요약.** Track A=조문별 위반 판정(설명가능 추론), Track B=광고 전체 오인위험 종합. 워크플로우에서 Track B는 Track A judge 호출(`workflow.py:422`)보다 앞선 `workflow.py:249`(`self.overall_impression.judge(...)`)에서 실행된다.

**`Claim->Meaning->Implicature->ConsumerEffect` 경로.** 이 경로는 (1) 데이터 모델과 (2) Track B 산출에 나타난다. `Claim` dataclass가 `meaning`·`implicature`·`consumer_effect` 필드를 보유(`schemas.py:158-160`). Track B는 grounded된 각 claim에 대해 `evidence_paths`를 만들며 경로 문자열을 명시적으로 박는다: `"path": "Claim -> Meaning -> Implicature -> ConsumerEffect -> OverallImpressionStandard"`(`overall_impression.py:126`)이고 각 단계 값을 `claim.text`/`claim.meaning`/`claim.implicature`/`claim.consumer_effect`로 채운다(`overall_impression.py:127-131`). 즉 코드상 이 4단계 경로는 Track B에서 명시적 산출 구조로 나타나며, Track A judge의 산출(`LLMJudgment`)에는 이 경로 문자열이 직접 등장하지 않는다.

### 규칙 판정과 LLM 판정의 결합 — 그리고 미연결 사실

`rule_judgment.py`는 결정론적 규칙 트랙을 정의한다: `build_rule_findings()`(`rule_judgment.py:57`)가 필수고지 존재/부재를 `PRESENT/MISSING`으로 판정하고, `rule_verdict()`(`rule_judgment.py:79`)가 `pass_candidate/needs_review/revise/reject`를 낸다(예금자보호·원금손실 누락이나 2건 이상 누락 시 `revise`, `rule_judgment.py:89-92`). 결합 함수는 `fuse_verdict(llm_verdict, rule_v)`(`rule_judgment.py:95`)로, `VERDICT_RANK`(`rule_judgment.py:41`)를 비교해 "규칙은 verdict를 올릴 수만 있다(escalate-only), 내리지 않는다"는 정책을 구현한다.

**불확실/주의: 이 모듈은 현재 파이프라인에 연결되어 있지 않다.** 저장소 전역 grep 결과 `fuse_verdict`·`rule_verdict`·`build_rule_findings`·`resolve_product_group`의 호출처가 `rule_judgment.py` 자신 외에 전혀 없으며, `import rule_judgment`/`from rule_judgment` 구문도 `workflow.py`·`router.py` 등 어디에도 없다(grep `--include=*.py .` 무결과). 즉 README/모듈 docstring이 기술하는 "규칙 트랙이 라우팅에 escalate-only로 합류"(`rule_judgment.py:8-11`, `95-97`)는 코드 의도일 뿐, 정적 코드상 LLM 판정과의 실제 fusion 호출은 확인되지 않는다(이 모듈이 의존하는 `build_disclosure_checks`는 `product_facts.py`에서 다른 경로로 쓰이지만, `rule_judgment.py`의 fusion 함수들은 호출되지 않음). 실제 결합되는 것은 LLM Track A 판정과 **예외 오버라이드**다(아래).

**예외 오버라이드 결합.** `NON_COMPLIANT` 판정에 한해(`workflow.py:446`) `review_exception()`(`judge.py:288`, name=`graphcompliance_exception_override`)이 closure 증거만으로 완화 여부를 판정하고, `effective_judgments()`(`router.py:155`)가 `OVERRIDE_TO_COMPLIANT`→COMPLIANT, `DOWNGRADE_TO_REVIEW`→INSUFFICIENT로 effective verdict를 만든다(`router.py:163-182`).

**판정 출력 스키마(금감원 회답식).** `LLMJudgment` dataclass(`schemas.py:262`)의 4필드가 "정의→요건→결론→유보" 구조를 그대로 담는다(주석 `schemas.py:272`):
- **정의** = `legal_basis`(`schemas.py:273`; 스키마 `judge.py:50`) — 근거 조문이 금지·요구하는 행위를 한 문장으로.
- **요건** = `criteria_findings`(`schemas.py:274`; 스키마 `judge.py:53-65`) — `{criterion, satisfied, finding}` 배열로 각 요건별 사실 적용.
- **결론** = `conclusion`(`schemas.py:275`; 스키마 `judge.py:67`) — 종합 판단 근거.
- **유보** = `reservation`(`schemas.py:276`; 스키마 `judge.py:69`) — "구체적 사실관계에 따라 달라질 수 있다"는 한정.

이 필드들은 `judge()`의 결과 매핑(`judge.py:275-278`)에서 채워진다. `legal_test`의 요건은 `build_legal_test()`가 `profile.required_positive_features`를 criterion으로, `matched_required_features`로 충족 여부(`rule_satisfied`)를, `anchor.feature_set.evidence`로 뒷받침 사실(`matched_facts`)을 제시한다(`judge.py:376-392`).

**할루시네이션/누설 차단(판정 단계).** `grounded_judgment_row()`(`judge.py:397`)가 `evidence_span`이 해당 anchor의 격리 증거창 밖이면(cross-anchor leakage) verdict를 강제로 `INSUFFICIENT`로 강등하고 score를 0.5로 캡한다(`judge.py:407-415`). 검사는 `evidence_span_belongs_to_anchor()`(`judge.py:418`)가 공백 정규화 후 anchor의 span+facts 내 포함 여부로 판정. 또한 anchor가 없거나(`judge.py:179`) judge가 행을 반환하지 않은 plan item은 `missing_judgment()`(`judge.py:429`)로 `INSUFFICIENT` 백필해 "모든 CUPlan 항목 커버리지"를 보장한다(`judge.py:281-285`).

### Prominence / Disclosure Gate(`prominence.py`)

이 모듈은 최종 판정을 내리지 않고 진단(diagnostic)만 산출한다(`prominence.py:3-7`). 핵심은 "고지가 존재함" vs "혜택을 완화할 만큼 현저(prominent)함"의 구분이다.

**혜택주장 vs 고지 비교.** 위계 점수표 `PROMINENCE_SCORE`(headline 4 … footnote 1, `prominence.py:19-25`). `build_disclosure_links()`(`prominence.py:79`)가 혜택 문장(`BENEFIT_ROLES`, `prominence.py:27`)과 고지 문장(`DISCLOSURE_ROLES`, `prominence.py:28`) 쌍마다 `prominence_gap = benefit_score - disclosure_score`(`prominence.py:90`)를 계산하고, gap>0이면 link status를 `PROMINENCE_INSUFFICIENT`로 표시(`prominence.py:102`).

**`PROMINENCE_INSUFFICIENT` 산출 위치.** `build_diagnostics()`(`prominence.py:108`)가 혜택 문장별로 가장 위계차가 작은 link(`best_link`, `prominence.py:123`)를 골라 그것마저 gap>0이면 `diagnostic_code: "PROMINENCE_INSUFFICIENT"`를 발화(`prominence.py:124-137`). 동위계 이상 고지가 하나라도 있으면 발화하지 않도록 best 기준으로 묶는다(`prominence.py:116-118`).

**`CONDITION_MISSING` 산출 위치.** `apply_comparison_diagnostics()`(`prominence.py:163`)에서 product fact 비교가 `SUPPORTED`였더라도 해당 문장이 `DISCLOSURE_MISSING` 진단 대상이면 status를 `CONDITION_MISSING`으로 덮어쓴다(`prominence.py:183-185`). 마찬가지로 `PROMINENCE_INSUFFICIENT` 문장이면 비교 status를 `PROMINENCE_INSUFFICIENT`로 덮어쓴다(`prominence.py:180-182`). 또한 누락 고지(`DISCLOSURE_MISSING`)는 `MISSING`/`PRESENT_BUT_NEGATED`/`IN_PRODUCT_DOC_ONLY` 상태이고 gate가 OFF가 아닌 필수 체크에서만 발화한다(`prominence.py:139-159`; gate 적용 필드 `PROMINENCE_REQUIRED_CHECK_IDS`, `prominence.py:41-45`). 이 갱신된 `comparison_results`·`prominence_diagnostics`가 product_fact_context에 다시 실려(`prominence.py:187-188`) Track B(`overall_impression.py:59-68`)와 수정안 컨텍스트로 전달된다.

### 수정안 생성(`revision.py`)

`LLMRevisionSuggester.suggest()`(`revision.py:289`)가 단일 LLM 호출(`revision.py:328`, name=`graphcompliance_revision_suggestions`)로 per-span 교정 카피를 만든다.

**생성 대상 게이팅.** effective 판정 중 `verdict == "NON_COMPLIANT"`인 것만 risk_row로 삼고 `INSUFFICIENT`는 제외(`revision.py:304-305`), actionable anchor type·display role도 함께 필터(`revision.py:297-299`). per-span 위반이 없어도 누락 고지나 Track B(MEDIUM/HIGH)가 있으면 생성한다(`needs_revision`, `revision.py:320-324`).

**원문↔교정본 diff.** 산출 스키마 `REVISION_SCHEMA`(`revision.py:243`)의 각 suggestion은 `before`/`after`/`risky_text`/`notes_for_reviewer`를 가진다(`revision.py:258-260`). 프론트는 이 `before`↔`after`를 span 단위 diff로 렌더한다. 전체 문서 교정본은 `DOCUMENT_REVISION_ANCHOR = "__document__"` 센티넬(`revision.py:282`)로 실어 원문↔교정본 문서 diff로 렌더하도록 설계됐으나, 시스템 프롬프트는 `integrated_revision`을 "파이프라인 미사용"으로 명시하고 per-span `after`에 집중하라고 지시한다(`revision.py:353-354`). 누락 고지는 문장에 끼우지 않고 하단 `__disclosure_block__`(`revision.py:185`) "꼭 확인해 주세요" 블록으로 모은다(`build_disclosure_block()` `revision.py:213`, `render_disclosure_block()` `revision.py:236`).

**할루시네이션 차단 장치(다층).**
1. **고정 보일러플레이트 사전** `DISCLOSURE_NOTICE_TEXT`(`revision.py:193-208`) — 누락 고지는 LLM이 아니라 이 상수 문구로만 추가. 상품별 값(심의필 번호·판매업자명)이 필요한 고지는 `DISCLOSURE_ADVISORY_ONLY`(`revision.py:210`)로 분류해 `status='reviewer'`(심사자 보완)로 둬 자동 생성하지 않는다(`revision.py:231-232`; 주석 `revision.py:182-184`, `217`).
2. **gate 범위 검사** `_gate_on()`(`revision.py:188`) — 적용범위(상품군·채널) 밖 고지를 누락으로 오인하지 않게 `gate_status==ON`인 것만 missing/block 대상(`revision.py:155-159`, `224`).
3. **조언↔카피 분리** `is_instruction_like()`(`revision.py:77`)가 `INSTRUCTION_ENDINGS`/`INSTRUCTION_MARKERS`(`revision.py:51-74`)로 "~하세요·병기·표시" 같은 지시문이 `after`(광고에 붙일 카피)에 새는 것을 거부. `suggestion_is_usable()`(`revision.py:416`)가 `after`가 비었거나 `before`/anchor 원문과 같거나(no-op) `GENERIC_INSTRUCTION_PREFIXES`로 시작하거나 instruction-like면 제외(`revision.py:423-429`).
4. **anchor 원문 결속** `suggestion_is_usable()`은 `anchor_text_by_id`(`revision.py:365`)에 없는 anchor_id의 제안을 버려(`revision.py:419`), LLM이 존재하지 않는 span을 지어내는 것을 차단.
5. **교정본 무결성 검증** `validate_integrated_revision()`(`revision.py:115`)이 전체 교정본에 대해 공백만 다른 no-op(`revision.py:127`), 조언 과반(`DOC_MAX_ADVICE_LINE_RATIO`, `revision.py:133`), 불릿·화살표 목록(`revision.py:137`), 원문 60% 미만 조각(`DOC_MIN_LENGTH_RATIO`, `revision.py:140`), 원문 단어 보존율 30% 미만(`_word_overlap`, `DOC_MIN_WORD_OVERLAP`, `revision.py:143`)을 거부하고 실패 시 `None`(문서 미첨부)을 반환한다.
6. **안전 폴백** LLM 제안이 전부 필터링되면 `fallback_suggestions()`(`revision.py:433`)가 고정된 안전 기본 교정안을 제시(`revision.py:441-451`).

또한 시스템 프롬프트가 "외부 법 인용 금지", "상품명·scope anchor 수정 금지", "고지 문장을 `after`에 삽입 금지(시스템이 별도 블록으로 추가)"를 명시(`revision.py:333-352`)해 LLM의 자의적 생성 범위를 좁힌다.

### `policy_evidence.py`의 역할 — 근거 조문 추적

런타임 전용 "정책 근거 사슬" 아티팩트를 만들어 심사 설명·감사 추적에 쓴다(v1은 Neo4j 노드를 만들지 않음, `policy_evidence.py:3-6`). 진입점 `build_policy_evidence_chains()`(`policy_evidence.py:16`)가 CU별로 세 종류 사슬을 생성:
- **`legal_basis_chain()`**(`policy_evidence.py:47`) — `source_article`(root_article)→`principle`(SalesPrinciple)→위임 표준 노드로 이어지는 법령 위임 사슬. `delegation_edges_for()`(`policy_evidence.py:88`)가 광고규제 토큰("광고", "금소법 제22조", "표시", "고지")이 있으면 "법률→시행령→감독규정/심의기준" `DELEGATES_TO` 엣지를 박는다(`policy_evidence.py:94-112`).
- **`disclosure_chain()`**(`policy_evidence.py:116`) — `matching_disclosures()`(`policy_evidence.py:174`)가 토큰 그룹(rate/condition/protection/risk/fee/review, `policy_evidence.py:187-194`)으로 CU와 필수고지 후보를 매칭해 보완 고지 후보를 사슬로 묶는다.
- **`exception_chain()`**(`policy_evidence.py:153`) — `legal_element_profile.exception_eligible`이면 `INCOMPLETE`, 아니면 `NOT_FOUND`(`policy_evidence.py:154-160`).

각 사슬은 `provenance_snippets()`(`policy_evidence.py:207`)로 `legal_evidence_ids`↔`evidence_texts`(상위 3개) 근거 스니펫을 첨부하고, 미완성 사슬은 `chain_diagnostic()`(`policy_evidence.py:217`)로 진단에 모은다. 이 사슬들은 Track A judge로 흘러들어가는데, `chains_for_plan_item()`(`judge.py:448`)이 `status == "FOUND"`인 사슬만 plan_item별로 필터해 `EvidenceWindow.policy_evidence_chains`(`schemas.py:258`)에 실어주고(`build_evidence_windows()`, `judge.py:153`), judge 프롬프트가 이 "위임 사슬(법률→시행령→감독규정→심의기준)을 인용"하도록 요구한다(`judge.py:209-212`). 즉 `policy_evidence.py`는 판정의 `legal_basis`/`conclusion`이 근거 조문에 결속되도록 추적 자료를 공급한다.

---

## 3. Neo4j 스키마 (코드 실측)

### 3.1 노드 라벨 전수 (생성/MATCH 근거)

저장소 .py 코드의 Cypher 문자열에서 추출한 노드 라벨은 다음과 같다. 라벨은 **두 부류**로 나뉜다: (A) 본 저장소 코드가 직접 `MERGE/CREATE`로 생성하는 라벨, (B) 코드가 `MATCH`로만 읽고(=별도 사전 적재 파이프라인이 생성), 본 저장소 .py에는 생성 구문이 없는 라벨.

확인 방법: `grep -rnE "(MERGE|CREATE) \([a-zA-Z_]*:(ComplianceUnit|LegalChunk|LegalClause|LawArticle|ExceptionRule)\b" *.py` → 매치 0건(exit 1). 즉 `ComplianceUnit, LegalChunk, LegalClause, LawArticle, ExceptionRule`는 본 저장소가 생성하지 않고 읽기만 한다.

| 라벨 | 핵심 프로퍼티 | 생성/참조 위치 | 비고 |
|---|---|---|---|
| `AdDraft` | `id, workspace_id, title, text, channel, source_type, product_group, content_hash, source` | `persistence.py:53`, props `persistence.py:63-71` | 광고 초안 |
| `ReviewRun` | `id, workspace_id, overall_impression_judgment, context_frame, sentence_units, inter_sentence_relations, context_influences, anchor_feature_sets, product_context, product_fact_context, disclosure_requirements, track_c_summary, retrieval_diagnostics` | `persistence.py:55`, props `persistence.py:72-88` | 복합값은 `neo4j_props()`(`persistence.py:690`)로 JSON 문자열 직렬화 |
| `Claim` | `id, text, span_start, span_end, risk_hypernym, risk_severity` | `persistence.py:104`, props `persistence.py:128-136` | |
| `Meaning` | `id, text` | `persistence.py:107`, props `:137` | `id=meaning_{claim_id}` |
| `Implicature` | `id, text` | `persistence.py:109`, props `:138` | `id=implicature_{claim_id}` |
| `ConsumerEffect` | `id, text` | `persistence.py:111`, props `:139` | `id=effect_{claim_id}` |
| `RiskNode` | `id, name, severity` | `persistence.py:113`, props `:140` | `id=risk_{claim_id}` |
| `ContextEntity` | `id, name, entity_type, span_start, span_end` | `persistence.py:146`, props `:154-164` | |
| `ClaimQualifier` | `id, text, role, span_start, span_end, meaning, risk_reason, confidence` | `persistence.py:170`, props `:178-191` | |
| `ContextFrame` | `frame_id(=id), summary, primary_message, product_purpose, tone, representative_consumer_impression, risk_axes, overall_risk_level` | `persistence.py:199`; 스키마 `schemas.py:86-94` | id 기본값 `context_frame_{review_run_id}`(`persistence.py:206`) |
| `SentenceUnit` | `id(=sentence_id), index, text, span, role, local_meaning, context_effect, risk_level, prominence_tier` | `persistence.py:214`; 스키마 `schemas.py:98-107` | |
| `InterSentenceRelation` | `id(=relation_id), source_sentence_id, target_sentence_id, relation_type, explanation, evidence` | `persistence.py:248`; 스키마 `schemas.py:111-125` | |
| `ContextInfluence` | `id(=influence_id), source_id, source_type, target_id, target_type, influence_type, effect, risk_delta, confidence` | `persistence.py:266`; 스키마 `schemas.py:129-138` | |
| `ContextTriple` | `id(=triple_id), claim_id, ...` | `persistence.py:284`, props `:293` | |
| `ContextAnchor` | `id(=anchor_id), anchor_type, text, span_start, span_end, facts_json` | `persistence.py:301`, props `:320-328` | |
| `PolicyHypernymProposal` | `id(=proposal_id), hypernym_id, hypernym, support, confidence, normalized_score, evidence_ids, why` | `persistence.py:306`, props `:329-342` | 런타임 앵커→하이퍼님 제안 |
| `PolicyHypernym` | `id, workspace_id` (정규 카탈로그) | 런타임 `OPTIONAL MATCH` `persistence.py:310`; 생성은 `policy_compiler.py:527`(`MERGE (h:PolicyHypernym {id,workspace_id})`, `SET h += row`) | 컴파일러가 적재 |
| `AnchorFeatureSet` | `id(=feature_set_id), ...` | `persistence.py:348`, props `:357` | |
| `CUPlan` | `id, workspace_id` | `persistence.py:364` | `id=cuplan_{review_run_id}` |
| `CUPlanItem` | `id(=plan_item_id), anchor_id, cu_id, ...` | `persistence.py:379`, props `:396` | |
| `ComplianceUnit` | `id, workspace_id, active_for_gate, principle, subject, condition, constraint, context, cu_type, severity, source_evidence/summary/text` (읽기) | **MATCH 전용**: `persistence.py:384`, `policy_compiler.py:350·573`, 프로퍼티는 `policy_compiler.py:361-370` RETURN에서 확인 | 본 저장소가 생성하지 않음(외부 적재) |
| `EvidenceWindow` | `id(=evidence_window_id), plan_item_id, legal_evidence_ids, ...`(단 `policy_evidence_chains`는 제외) | `persistence.py:407`, props `:399-423` | |
| `LLMJudgment` | `id(=judgment_id), plan_item_id, ...` | `persistence.py:431`, props `:445` | |
| `ExceptionReview` | `id(=exception_review_id), judgment_id, closure_evidence_ids, ...` | `persistence.py:451`, props `:467` | 런타임 산출 (cf. 정적 `ExceptionRule`과 다름) |
| `ProductGroup` | `id(=product_group_{group}), name, workspace_id, source, created_at, updated_at` | 런타임 `persistence.py:475`; 적재 `load_product_graph.py:222` props `:97-107` | |
| `DisclosureRequirement` | `id, label, source, why, product_group, workspace_id, created_at, updated_at`; 정제 카탈로그는 추가로 `product_groups`(배열), `source='agentic_policy_inventory'` | 런타임 `persistence.py:490`; 적재 `load_product_graph.py:279`; 조회 `disclosure_catalog.py:374` | §9 상세 |
| `Product` | `id, name, product_group, major, subcategory, category, workspace_id, source, document_count, document_labels, source_ids` | 적재 `load_product_graph.py:246` props `:119-133`; 런타임 `persistence.py:508·546` | |
| `ProductDocument` | `id, product_id, product_name, product_group, label_id, label, major, subcategory, category, extension, size_bytes, file_name, relative_path, original_name, exists, metadata_source` | 적재 `load_product_graph.py:261` props `:134-154`; 런타임 `persistence.py:514·564` | |
| `DocumentLabel` | `id, name, workspace_id, source` | `load_product_graph.py:234` props `:108-118` | |
| `ProductFact` | `id(=fact_id), fact_type, value, unit, condition, source_document_id, page_or_chunk, evidence_text, confidence, matched_product` | 런타임 `persistence.py:589`, props `:603`; 스키마 `product_facts.py:40-73` | |
| `ClaimFact` | `id(=claim_fact_id), claim_id, fact_type, value, unit, qualifier, evidence_text, confidence, prominence_tier` | 런타임 `persistence.py:616`, props `:630`; 스키마 `product_facts.py:76-95` | |
| `ComparisonResult` | `id(=comparison_id), claim_fact_id, product_fact_id, status, rationale, evidence_text, confidence` | 런타임 `persistence.py:648`, props `:686` | `status` enum `product_facts.py:106-114` |
| `Premise` | `id, workspace_id, premise_type, embedding, updated_at, ...` | `policy_compiler.py:537` props `:564` | |
| `CUEmbeddingProfile` | `id, workspace_id, embedding, updated_at, ...` | `policy_compiler.py:574` props `:585` | |
| `CULegalElementProfile` | `id, workspace_id, action_type, required_positive_features, applicability_scope, risk_title, exception_eligible, rationale, updated_at` | `policy_compiler.py:332·593` | |
| `ReviewRunSnapshot` | `id, workspace_id, output_json, + _summary 필드(title, channel, product_group, final_verdict, missing_disclosures, principles, cu_ids, cu_labels, ...)` | `run_store.py:33·159`, 요약 `run_store.py:76-132` | 리스트 필드는 JSON 문자열화 `run_store.py:35·153` |
| `LawArticle` | (읽기) `id, workspace_id` | **MATCH 전용**: `build_cross_law_citations.py:101·147-148`, `legal_hierarchy.py:29` | 외부 적재 |
| `ExceptionRule` | (읽기) `id, workspace_id` | **MATCH 전용**: `bridge_exception_rules.py:78·116` | 외부 적재 |
| `LegalClause` | (읽기) `id, text, article_no, document_title` | **MATCH 전용**: `policy_compiler.py:358`, RETURN `:372-376` | 외부 적재 |
| `LegalChunk` | (읽기) `id, text, article_no, document_title` | **MATCH 전용**: `policy_compiler.py:359`, RETURN `:377-382` | 외부 적재 |

불확실: `ComplianceUnit/LegalChunk/LegalClause/LawArticle/ExceptionRule`의 노드 생성(적재) 스크립트는 본 저장소 루트 .py에 없다(grep 결과 생성 구문 0건). 이들의 전체 프로퍼티 스키마는 코드의 RETURN/MATCH에서 참조되는 필드(위 표)로만 부분 확인되며, 권위 있는 정의는 외부 ingestion 파이프라인에 있다.

### 3.2 관계 타입 전수와 방향

근거: 모두 `persistence.py`, `policy_compiler.py`, `load_product_graph.py`, `bridge_exception_rules.py`, `build_cross_law_citations.py`, `retriever.py`의 Cypher.

ReviewRun 본체 (persistence.py):
- `(AdDraft)-[:HAS_REVIEW_RUN]->(ReviewRun)` (`:57`)
- `(ReviewRun)-[:HAS_CLAIM]->(Claim)` (`:106`)
- `(Claim)-[:DENOTES]->(Meaning)`, `(Meaning)-[:IMPLIES]->(Implicature)`, `(Implicature)-[:CAN_MISLEAD]->(ConsumerEffect)`, `(ConsumerEffect)-[:RAISES]->(RiskNode)` (`:115-118`)
- `(Claim)-[:MENTIONS_ENTITY]->(ContextEntity)` (`:148`)
- `(Claim)-[:HAS_QUALIFIER]->(ClaimQualifier)` (`:172`)
- `(ReviewRun)-[:HAS_CONTEXT_FRAME]->(ContextFrame)` (`:201`)
- `(ReviewRun)-[:HAS_SENTENCE_UNIT]->(SentenceUnit)`, `(ContextFrame)-[:HAS_SENTENCE]->(SentenceUnit)` (`:216·218`)
- `(SentenceUnit)-[:CONTAINS_CLAIM]->(Claim)` (`:235`)
- `(SentenceUnit)-[:HAS_INTER_SENTENCE_RELATION]->(InterSentenceRelation)`, `(InterSentenceRelation)-[:RELATES_TO_SENTENCE]->(SentenceUnit)` (`:250-251`)
- `(ReviewRun)-[:HAS_CONTEXT_INFLUENCE]->(ContextInfluence)` (`:268`)
- `(Claim)-[:HAS_CONTEXT_TRIPLE]->(ContextTriple)` (`:286`)
- `(Claim)-[:HAS_ANCHOR]->(ContextAnchor)` (`:303`)
- `(ContextAnchor)-[:NORMALIZED_TO]->(PolicyHypernymProposal)` (`:308`), `(PolicyHypernymProposal)-[:SELECTS_HYPERNYM]->(PolicyHypernym)` (`:312`)
- `(ContextAnchor)-[:HAS_FEATURE_SET]->(AnchorFeatureSet)` (`:350`)
- `(ReviewRun)-[:HAS_CU_PLAN]->(CUPlan)` (`:366`)
- `(CUPlan)-[:HAS_PLAN_ITEM]->(CUPlanItem)`, `(ContextAnchor)-[:SELECTED_FOR_PLAN]->(CUPlanItem)`, `(CUPlanItem)-[:TARGETS_CU]->(ComplianceUnit)` (`:381·382·386`)
- `(CUPlanItem)-[:HAS_EVIDENCE_WINDOW]->(EvidenceWindow)`, `(EvidenceWindow)-[:USES_EVIDENCE]->(evidence)` (`:409·414`)
- `(CUPlanItem)-[:JUDGED_AS]->(LLMJudgment)`, `(LLMJudgment)-[:USES_EVIDENCE]->(EvidenceWindow)` (`:433·437`)
- `(LLMJudgment)-[:HAS_EXCEPTION_REVIEW]->(ExceptionReview)`, `(ExceptionReview)-[:USES_EVIDENCE]->(evidence)` (`:453·458`)

상품/고지 컨텍스트 (persistence.py):
- `(ReviewRun)-[:SCOPED_TO_PRODUCT_GROUP]->(ProductGroup)` (`:477`)
- `(ProductGroup)-[:REQUIRES_DISCLOSURE]->(DisclosureRequirement)`, `(ReviewRun)-[:CHECKS_DISCLOSURE]->(DisclosureRequirement)` (`:492·493`)
- `(ProductGroup)-[:HAS_PRODUCT]->(Product)`, `(ReviewRun)-[:ABOUT_PRODUCT]->(Product)`, `(Product)-[:HAS_PRODUCT_DOCUMENT]->(ProductDocument)` (`:510·511·516`)
- `(ReviewRun)-[:USES_PRODUCT_DOCUMENT]->(ProductDocument)` (`:566`)
- `(ReviewRun)-[:EXTRACTED_PRODUCT_FACT]->(ProductFact)`, `(ProductDocument)-[:CONTAINS_FACT]->(ProductFact)` (`:591·595`)
- `(ReviewRun)-[:EXTRACTED_CLAIM_FACT]->(ClaimFact)`, `(Claim)-[:ASSERTS_FACT]->(ClaimFact)` (`:618·622`)
- `(ReviewRun)-[:HAS_COMPARISON_RESULT]->(ComparisonResult)`, `(ClaimFact)-[:HAS_COMPARISON_RESULT]->(ComparisonResult)`, `(ClaimFact)-[:COMPARED_TO]->(ComparisonResult)`, `(ComparisonResult)-[:COMPARES_TO]->(ProductFact)`, `(ClaimFact)-[:COMPARED_TO]->(ProductFact)`, `(ComparisonResult)-[:EVIDENCED_BY]->(ProductDocument)`, `(ComparisonResult)-[:SUPPORTS_JUDGMENT]->(LLMJudgment)` (`:650·654·657·662·665·670·675`)

상품그래프 적재 (load_product_graph.py):
- `(ProductGroup)-[:HAS_PRODUCT]->(Product)` (`:250`)
- `(Product)-[:HAS_PRODUCT_DOCUMENT]->(ProductDocument)`, `(ProductDocument)-[:HAS_DOCUMENT_LABEL]->(DocumentLabel)` (`:265·268`)
- `(ProductGroup)-[:REQUIRES_DISCLOSURE]->(DisclosureRequirement)` (`:283`)

정책 정렬층 (policy_compiler.py):
- `(source)-[:DERIVES_PREMISE]->(Premise)` (`:543`)
- `(Premise)-[:DEFINES_HYPERNYM]->(PolicyHypernym)` (premise_type='definition'일 때), `(Premise)-[:SUPPORTS_HYPERNYM]->(PolicyHypernym)` (그 외) (`:549·552`)
- `(Premise)-[:SUPPORTS_CU]->(ComplianceUnit)` (`:558`)
- `(ComplianceUnit)-[:HAS_EMBEDDING_PROFILE]->(CUEmbeddingProfile)` (`:576`)
- `(ComplianceUnit)-[:HAS_SUBJECT_HYPERNYM]->(PolicyHypernym)` (`:580`)
- `(ComplianceUnit)-[:HAS_LEGAL_ELEMENT_PROFILE]->(CULegalElementProfile)` (`:337·595`)
- 읽기 전용 경로: `(LegalClause)-[:GROUNDS_CU]->(ComplianceUnit)`, `(LegalChunk)-[:EVIDENCES_CU]->(ComplianceUnit)`, `(ComplianceUnit)-[:GROUNDED_IN|HAS_SOURCE_CHUNK]->(direct)` (`:358·359·360`)

기타 보강·검색 (외부 적재 노드 대상):
- `(ComplianceUnit)-[:HAS_EXCEPTION]->(ExceptionRule)` 생성 `bridge_exception_rules.py:117`; 문서상 `ExceptionRule-[:REQUIRES_EVIDENCE]->EvidenceRequirement` (`bridge_exception_rules.py:4`)
- `(LawArticle)-[:CITES_ARTICLE]->(LawArticle)` 생성 `build_cross_law_citations.py:149`
- 검색 경로(MATCH): `(cu)-[:REFERS_TO|DERIVES|GROUNDED_IN|HAS_SOURCE_CHUNK|HAS_EXCEPTION|REQUIRES_EVIDENCE*1..depth]->(node)` (`retriever.py:293`), `(cu)-[:GROUNDED_IN|HAS_SOURCE_CHUNK|EVIDENCES_CU]-(direct_evidence)` (`retriever.py:206`)

모든 관계는 공통 프로퍼티 `{workspace_id, source}`(+런타임 관계는 `review_run_id`)를 가진다 (예: `persistence.py:57`, `load_product_graph.py:250`).

### 3.3 인덱스/제약

- `CREATE CONSTRAINT`: 본 저장소 .py에 **없음** (grep 0건). 불확실: 유니크 제약은 외부 스키마 초기화에서 관리될 수 있음.
- 벡터 인덱스 2종 (`policy_compiler.py:_ensure_vector_indexes()` `:604-622`):
  - `premise_embedding_vector` — `FOR (p:Premise) ON (p.embedding)`, `cosine`, 차원=런타임 임베딩 차원 (`:611-613`)
  - `cu_embedding_profile_vector` — `FOR (p:CUEmbeddingProfile) ON (p.embedding)`, `cosine` (`:618-620`)
  - 둘 다 `IF NOT EXISTS`. 일반 RANGE/FULLTEXT 인덱스 생성 구문은 없음.

---

## 4. 법령 적재(ingestion) 파이프라인

**전체 단계와 노드 산출 흐름.** 본 저장소에 포함된 적재 코드는 "원문 → Markdown/Chunk" 의 *원시 파싱* 단계가 아니라, 이미 Neo4j에 적재된 법령 코퍼스(`LawArticle`/`LegalClause`/`LegalChunk`)와 큐레이션된 `ComplianceUnit`(CU)을 입력으로 받아 논문형 정렬(alignment) 레이어를 합성하는 *컴파일* 단계다. `policy_compiler.py:1-11` docstring이 명시: `LegalClause/LegalChunk -> Premise -> PolicyHypernym`, `Premise -> ComplianceUnit -> CUEmbeddingProfile`. 즉 이 파이프라인의 입력 단위는 청크가 아니라 **활성 CU**다(`_load_policy_sources()` 의 `MATCH (cu:ComplianceUnit ...) WHERE coalesce(cu.active_for_gate, false) = true`, `policy_compiler.py:350-351`). 원문→Markdown/청크 분할을 수행하는 스크립트는 본 6개 파일에 없음(불확실: 청크 자체는 외부 적재 단계 산물로 가정됨, 근거는 `_load_policy_sources()`가 `LegalClause)-[:GROUNDS_CU]->(cu)` 와 `LegalChunk)-[:EVIDENCES_CU]->(cu)` 를 *조회만* 한다는 점, `policy_compiler.py:358-359`).

**단계별 스크립트/함수.**
1. **소스 적재(읽기):** `PolicyAlignmentCompiler._load_policy_sources()` (`policy_compiler.py:344-392`) — 활성 CU와 그에 연결된 `LegalClause`/`LegalChunk`/직접 근거(`GROUNDED_IN|HAS_SOURCE_CHUNK`)를 최대 4개씩 모아 배치 입력 행을 만든다.
2. **배치 컴파일(LLM):** `PolicyAlignmentCompiler.compile()` (`policy_compiler.py:167-202`)가 소스를 `batch_size`로 쪼개 `_compile_batch()` (`policy_compiler.py:394-433`) 호출. `_compile_batch()`는 `self.llm.structured(...)`로 `COMPILER_SCHEMA`(`policy_compiler.py:49-136`)에 맞춘 구조화 출력을 생성 — `policy_hypernyms`, `premises`, `cu_profiles`, `cu_legal_element_profiles` 4종을 한 번에 산출. 최대 3회 재시도하며 `repair_compiler_cu_ids()`(`:706-737`) + `validate_compiler_output()`(`:663-703`)로 검증. 결정적 폴백 없음(`policy_compiler.py:9-10`).
3. **정규화:** `_normalize_compiled()` (`policy_compiler.py:435-519`) — hypernym에 `stable_id` 부여, premise/cu_profile 임베딩 생성(`self.embedder.embed_many`, `:469,487`), legal-element 프로파일 빌드.
4. **그래프 기록:** `_write_compiled()` (`policy_compiler.py:521-602`) — `PolicyHypernym`/`Premise`/`CUEmbeddingProfile`/`CULegalElementProfile` 노드를 `MERGE`하고 관계(`DERIVES_PREMISE`, `DEFINES_HYPERNYM`/`SUPPORTS_HYPERNYM`, `SUPPORTS_CU`, `HAS_EMBEDDING_PROFILE`, `HAS_SUBJECT_HYPERNYM`, `HAS_LEGAL_ELEMENT_PROFILE`)를 연결.
5. **벡터 인덱스 보장:** `_ensure_vector_indexes()` (`policy_compiler.py:604-622`) — `premise_embedding_vector`, `cu_embedding_profile_vector` 코사인 인덱스 생성.

**보조 적재 스크립트(같은 §4 범위, CU 생성과 무관한 그래프 보강).**
- `build_cross_law_citations.py` — `LawArticle` 텍스트의 축약 인용("법 제22조", "영 제20조" 등)을 파싱해 법령 간 `CITES_ARTICLE` 엣지를 `MERGE`(`extract_cross_law_refs()` `:69-82`, `main()` `:85-161`, source 태그 `cross_law_citation_builder` `:149`). CU/Premise를 만들지 않음.
- `legal_hierarchy.py` — 위 `CITES_ARTICLE` 엣지를 따라 하위 규정→모법(광고·권유 조문)을 매핑(`load_parent_map()` `:43-70`, `parent_articles_for()` `:73-87`). 런타임 조문 병기용 읽기 전용 헬퍼이며 Neo4j 미설정 시 빈 dict로 무력화(`:50-52`).
- `bridge_exception_rules.py` — 컴파일된 `cu_legal_*` CU와 큐레이션 `ExceptionRule`을 개념(action_type + risk_title 키워드 가드)으로 `HAS_EXCEPTION` 연결(`plan_links()` `:96-109`, `apply_links()` `:112-123`). docstring(`:1-29`)이 "demo-grade heuristic bridge"임을 명시. CU를 생성하지 않고 기존 CU에 엣지만 추가.

**★ "어느 함수가 ComplianceUnit을 생성하는가".** 본 6개 파일 어디에도 `ComplianceUnit` 노드를 *생성(CREATE/MERGE)* 하는 코드는 없다. 모든 경로가 CU를 `MATCH`로 *전제(precondition)* 한다: `_load_policy_sources()`(`:350`), `_write_compiled()`의 `MATCH (cu:ComplianceUnit {id: $cu_id ...})`(`:573,592`), `_write_legal_element_profiles()`(`:331`), `bridge_exception_rules.fetch_candidates()`(`:86`). 따라서 **CU 생성기는 이 파일 집합 밖에 존재**한다. 이 파이프라인이 CU에 대해 생성하는 것은 CU의 *부속 노드*다:
- `CUEmbeddingProfile` 생성: `_write_compiled()` 의 `MERGE (profile:CUEmbeddingProfile {id: $profile_id ...})` (`policy_compiler.py:574`). 입력: `compiled["cu_profiles"]` 각 행(`cu_id`, `subject_hypernym_ids`, `profile_summary`, `embedding_text`, `embedding`), 출력: 노드 + `(cu)-[:HAS_EMBEDDING_PROFILE]->(profile)` + `(cu)-[:HAS_SUBJECT_HYPERNYM]->(h)` (`:576-580`).
- `CULegalElementProfile` 생성: `_write_compiled()` 의 `MERGE (profile:CULegalElementProfile {id: $profile_id ...})` (`policy_compiler.py:593`), 빌드는 `build_legal_element_profile_from_compiler_row()`(`legal_elements.py:234-256`) 또는 텍스트 추론 `infer_legal_profile_from_text()`(`legal_elements.py:259-277`). 백필 경로는 `_write_legal_element_profiles()`(`policy_compiler.py:325-342`).
- `PolicyHypernym`/`Premise` 생성: `_write_compiled()` `:527`(hypernym `MERGE`), `:537`(premise `MERGE`).

**`policy_compiler.py` CLI 인자와 main 흐름.** `main()` (`policy_compiler.py:625-660`)의 argparse:
- `--workspace-id` (기본 `graphcompliance_mvp_jb_20260530`, `:627`)
- `--batch-size` (int, 기본 16, `:628`)
- `--max-batches` (int, 기본 None, `:629`)
- `--missing-active-links-only` (flag, `:630`) — 정렬 엣지가 누락된 CU만 대상
- `--legal-elements-only-from-existing-profiles` (flag, `:631`) → `backfill_legal_element_profiles()` 경로(`:204-243`)
- `--canonicalize-existing-legal-elements` (flag, `:632`) → `canonicalize_existing_legal_element_profiles()` 경로(`:245-284`)
- `--dry-run` (flag, `:633`), `--log-level` (기본 INFO, `:634`)

분기 우선순위(`:640-657`): `canonicalize` > `legal-elements-only` > 기본 `compile()`. `PolicyAlignmentCompiler.__init__`(`:140-159`)은 `NEO4J_URI` + (`NEO4J_USER`|`NEO4J_USERNAME`) + `NEO4J_PASSWORD` 미설정 시 `RuntimeError`. `compile()`은 활성 CU 소스가 0건이면 `RuntimeError("No active ComplianceUnit sources found in Neo4j.")` (`:177-178`).

---

## 5. ★ PolicyHypernym 어휘 (언어중립 ID인가 한국어 문자열인가)

**식별자/이름 프로퍼티.** `PolicyHypernym` 노드의 프로퍼티는 `_normalize_compiled()`(`policy_compiler.py:441-448`)에서 정해진다: `id`, `name`, `domain`, `description`, `priority`, `status`. 거버넌스 후에는 `vocabulary_governance.py:166-177`에서 `original_name`, `canonical_name_ko`, `description_ko`, `aliases`, `merge_key`, `governance_status` 등이 추가된다.

**개념 식별은 '한국어 문자열'이다(언어중립 ID 아님) — 코드 근거로 단정.** 핵심은 `id` 의 유도 방식이다. `stable_id("policy_hypernym", workspace_id, domain, name)` (`policy_compiler.py:440`)이고, `stable_id`는 입력 부분들을 `"||".join`한 뒤 SHA-256 해시(`utils.py:11-13`). 즉 `id`는 **한국어 `name` 문자열 자체의 해시**다. `name`이 한 글자라도 다르면 다른 id가 생성된다. 따라서 id는 언어중립 안정 키가 아니라 *한국어 라벨의 함수*다.

결정적으로, **`name`은 반드시 한국어여야 한다는 제약이 코드로 강제**된다:
- 컴파일러 시스템 프롬프트: "Every policy_hypernyms.name must be a Korean canonical label ... Do not use snake_case, English-only labels" (`policy_compiler.py:406-409`).
- 검증기 `validate_compiler_output()`이 `is_korean_canonical_label(name)` 미충족 시 에러를 발생시켜 재시도(`policy_compiler.py:666-668`).
- `is_korean_canonical_label()` (`policy_compiler.py:740-746`)은 `_`(snake_case)가 있으면 False, 그리고 **한글 음절(U+AC00–U+D7A3)이 하나도 없으면 False** — 즉 한글 포함을 *물리적으로 요구*.

`canonical_name_ko` / `aliases` 의 역할: `vocabulary_governance.py`의 2차 거버넌스 패스가 LLM으로 각 hypernym을 한국어 표준 라벨로 정규화한다. `_write_governed()` (`:166-177`)는 기존 `name`을 `original_name`으로 보존하고 `name`을 `canonical_name_ko`로 **덮어쓴다**(`:167-169`). `aliases`는 원래 라벨과 변형들을 담는 검색/병합용 동의어 목록이며, `validate_governance_output()`이 빈 aliases를 에러로 처리(`:198-199`). `merge_key`는 동의어 중복 hypernym 병합 후보 키. 즉 **표준명도 한국어, 별칭도(주로) 한국어** — 영어는 "주가연계증권(ELS)"처럼 한국어 문맥과 함께일 때만 허용(`:152-154`, `policy_compiler.py:406-408`). 어디에도 언어와 무관한 개념 코드(예: `CONCEPT_0001`, IRI, ISO 코드)는 없다.

**정의/생성/정규화 위치.** 생성: 컴파일러 LLM 출력(`COMPILER_SCHEMA.policy_hypernyms`, `policy_compiler.py:53-66`) → `_normalize_compiled()`에서 id 부여(`:440`) → `_write_compiled()`에서 `MERGE (h:PolicyHypernym ...)`(`:527-528`). 정규화: `VocabularyGovernance.govern()`(`vocabulary_governance.py:87-124`)이 `_govern_batch()`(`:145-158`)로 표준화하고 `_write_governed()`(`:160-182`)로 기록. canonicalize 함수는 *PolicyHypernym 라벨용 결정적 함수가 아니라* LLM 기반이다 — 본 모듈에 결정적 번역/정규화 폴백 없음(`vocabulary_governance.py:6-9`). (주의: `legal_elements.py`의 `canonicalize_required_features()`/`canonicalize_required_feature()` `:325-348`는 PolicyHypernym이 아니라 *legal-element feature id* 정규화용으로, 별개 어휘다.)

**캄보디아(크메르어/영어) 확장 함의 — 한 단락.** 현재 설계에는 **언어중립 개념 ID가 부재**하다. PolicyHypernym의 1차 식별자(`id`)가 한국어 `name`의 SHA-256 해시(`policy_compiler.py:440`, `utils.py:11-13`)이고, 한글 음절 포함이 `is_korean_canonical_label()`로 하드코딩 강제(`policy_compiler.py:744`)되며, 컴파일러·거버넌스 양쪽 검증기가 비한국어 라벨을 거부(`policy_compiler.py:666-668`, `vocabulary_governance.py:194-196`)하기 때문이다. 따라서 크메르어/영어로 캄보디아 법령을 적재하면, 같은 정책 개념(예: "원금보장")이라도 한국어 코퍼스와 크메르어 코퍼스에서 *서로 다른 id를 가진 별개 노드*로 갈라지며, 두 언어 간 개념 공유·교차 인용·동의어 병합이 자동으로 불가능하다. `aliases`/`merge_key`(`vocabulary_governance.py`)는 동의어를 모을 수 있으나 어디까지나 한국어 표준명에 종속된 보조 필드이고 언어중립 앵커가 아니다. 캄보디아 확장을 안전히 하려면, (a) `is_korean_canonical_label` 강제와 검증기 제약을 다국어 허용으로 완화하고, (b) `name`(언어별 표시 라벨)과 분리된 **언어중립 개념 코드**를 `stable_id`의 해시 입력으로 도입해 id가 한국어 문자열에 묶이지 않도록 재설계하는 것이 전제다. (불확실: 본 6개 파일 외에 별도 다국어/개념코드 메커니즘이 있는지는 이 범위에서 확인 불가.)

---

## 6. Claim 추출/정규화

### 6.1 위험표현/주장 추출 함수와 LLM 프롬프트 위치

추출 담당 클래스는 `LLMContextExtractor`(context_extractor.py:283). 진입은 `extract_hierarchical()`(context_extractor.py:290)이고, 환경변수 `CCG_CONTEXT_EXTRACTION_STAGED`(context_extractor.py:294)에 따라 두 경로로 분기한다.

- 단일 호출 경로 `_extract_hierarchical_legacy()`(context_extractor.py:310): `self.llm.structured(name="graphcompliance_context_extraction", schema=EXTRACTION_SCHEMA, ...)` 한 번으로 ContextFrame·SentenceUnit·관계·Claim을 모두 추출. system 프롬프트는 context_extractor.py:322~357에 정의. user 프롬프트는 `[title]/[channel]/[content_text]` 포맷(context_extractor.py:358~362).
- 단계 분할 경로 `_extract_hierarchical_staged()`(context_extractor.py:368): Stage 1 frame+sentence(`name="graphcompliance_context_sentences"`, system 프롬프트 :381~388), Stage 2 청크별 Claim 추출(`name="graphcompliance_context_claims"`, system 프롬프트 :412~425, 청크 크기 env `CCG_CONTEXT_CLAIM_CHUNK_SENTENCES` 기본 8 :405), Stage 3 관계/영향(`name="graphcompliance_context_relations"`, system 프롬프트 :455~462).

추출되는 위험표현/주장 스키마: `EXTRACTION_SCHEMA`(context_extractor.py:30)의 `claims` 항목(:145~239). 각 Claim은 `meaning`/`implicature`/`consumer_effect`/`risk_hypernym`/`risk_severity`(LOW/MEDIUM/HIGH)와 표현 단위 `qualifiers`(role enum: target_scope, condition_scope, certainty, guarantee, benefit_scope, risk_downplay, urgency, comparison, disclosure_qualifier, other — :167~180)를 가진다. LLM 응답 dict는 `_build_extraction_from_result()`(context_extractor.py:490)에서 `Claim`/`ClaimQualifier`/`ContextEntity` 데이터클래스로 변환되며 `stable_id(...)`로 ID가 부여된다(:570, :593).

추출 결과는 `build_context_triples()`(context_extractor.py:734)에서 감사 가능한 ER 트리플(`Claim --DENOTES--> Meaning`, `--IMPLIES--> Implicature`, `--CAN_MISLEAD--> ConsumerEffect`, `--RAISES--> RiskNode` 등 :838~877)로도 물질화된다.

### 6.2 PolicyHypernym/정규 라벨 매핑·정규화 코드

정규화는 `PolicyGuidedNormalizer.normalize()`(normalizer.py:66). 핵심 동작:
- 허용 vocabulary는 런타임에 `policy_context["hypernyms"]`에서 빌드(normalizer.py:74~78). 비어 있으면 RuntimeError(normalizer.py:79~80) — vocabulary는 코드 하드코딩이 아니라 retriever가 Neo4j에서 가져온 PolicyHypernym 노드에서 동적 주입된다.
- `normalization_schema_for_allowed_ids()`(normalizer.py:184)가 `hypernym_id` 필드의 enum을 승인된 id 목록으로 스키마 레벨에서 제약(:190). LLM이 임의 id를 반환하지 못하게 구조적으로 강제.
- LLM 호출 `self.llm.structured(name="graphcompliance_policy_normalization", ...)`(normalizer.py:110), system 프롬프트는 normalizer.py:113~124, user 프롬프트는 `[claims]/[allowed_policy_hypernyms]/[policy_premises]/[supporting_policy_fragments]`(normalizer.py:125~135).
- 반환된 anchor의 `claim_id` 유효성·`hypernym_id` 허용 여부를 재검증하고(normalizer.py:142~150), STRONG 지지 시 `normalized_score = min(1.0, confidence+0.3)`로 가중(normalizer.py:155). 산출물은 `ContextAnchor[]`(anchor_type: product/claim/risk/target_consumer_anchor — normalizer.py:29~31)로, 각 anchor에 `PolicyHypernymProposal[]`을 붙인다.
- 정규화 후 `fold_qualifier_anchors_into_parent_claims()`(claim_modeling.py:23)가 일반 scope/certainty/guarantee qualifier에 해당하는 standalone `target_consumer_anchor`를 부모 claim/risk anchor로 접어 넣는다(폴딩 대상 role 집합 claim_modeling.py:10~20).

### 6.3 언어 의존성 판정

판정: 이 단계는 강하게 한국어 의존적이다. 근거:
- 추출 system 프롬프트가 "Korean financial-advertising context graph extractor"로 명시되고(context_extractor.py:323, :382, :414), 위험표현 예시가 한국어 리터럴로 프롬프트에 하드코딩됨: `'누구나' -> target_scope`, `'조건 없이'/'제한 없이' -> condition_scope`, `'확정'/'반드시' -> certainty`, `'보장'/'원금보장' -> guarantee`, `'안정적 고수익' -> risk_downplay/benefit_scope` (context_extractor.py:336~341). 구체 세그먼트 예시도 `'고령층 고객'/'중위험 투자자'/'소상공인'` 한국어(:340~341).
- 정규화 프롬프트도 한국어 scope qualifier 리터럴을 하드코딩: `'누구나','전 고객','조건 없이','제한 없이','무조건','확정','보장'` (normalizer.py:120~123).
- 다만 매핑의 '정규 라벨' 자체(PolicyHypernym id/name)는 코드/프롬프트에 한국어로 고정된 게 아니라 Neo4j vocabulary에서 동적으로 주입되므로(normalizer.py:84~93), 라벨 집합은 데이터 의존이고 언어는 그 데이터의 언어를 따른다.
- 단, 다운스트림 텍스트 매칭 일부는 한국어 토큰에 직접 의존: `fold_qualifier_anchors_into_parent_claims`의 텍스트 비교는 공백 제거 후 문자열 일치라 언어 중립(claim_modeling.py:90~91)이나, workflow.py의 `exception_closure_has_mitigation_evidence()`는 한국어 토큰 리스트 `["예외","고지","설명","증거","상품사실","예금자보호","조건","승인","완화"]`로 부분 문자열 매칭(workflow.py:624~631) — 명백히 한국어 의존.

정규식 기반 추출은 발견되지 않음: Claim/qualifier 추출은 정규식이 아니라 LLM structured output에 의존한다(불확실 아님 — context_extractor.py 전체에 `re.`/정규식 패턴 부재). 따라서 "한국어 정규식"에는 묶여 있지 않으나 "한국어 프롬프트 리터럴"과 "한국어 토큰 매칭"에는 강하게 묶여 있다.

불확실: 실제 PolicyHypernym 라벨이 한국어인지 영문인지는 라이브 Neo4j 데이터에 따라 달라지며 정적 코드만으로는 확정 불가(쿼리 금지 조건상 미확인).

참고 경로: `/Users/kunwoo/Desktop/workspace/junbub/repo/workflow.py`, `/Users/kunwoo/Desktop/workspace/junbub/repo/context_extractor.py`, `/Users/kunwoo/Desktop/workspace/junbub/repo/normalizer.py`, `/Users/kunwoo/Desktop/workspace/junbub/repo/claim_modeling.py`, `/Users/kunwoo/Desktop/workspace/junbub/repo/router.py`, `/Users/kunwoo/Desktop/workspace/junbub/repo/risk_context.py`, `/Users/kunwoo/Desktop/workspace/junbub/repo/server.py`.

---

## 7. 검색/게이팅 메커니즘

### 후보 CU 검색 방식: (c) 혼합 (어휘 overlap + 임베딩 유사도)

DB Cypher(`candidates_for_anchor`, `retriever.py:170-269`)에서 두 신호를 동시에 계산한다.

- **임베딩 유사도(벡터)**: `vector.similarity.cosine(profile.embedding, $anchor_embedding) AS profile_vector_score` (`retriever.py:188`). 대상은 `ComplianceUnit -> CUEmbeddingProfile` 노드의 `profile.embedding` (`retriever.py:178-180`).
- **어휘 overlap(hypernym id/name 일치)**: seed hypernym과 CU가 연결한 hypernym의 교집합 크기. `size([id IN matched_hypernym_ids WHERE id IN seed_ids]) AS id_overlap_count` 및 `name_overlap_count` (`retriever.py:196-197`). 이는 토큰 string overlap이 아니라 그래프 노드 식별자/정규화명 집합 교집합.
- **후보 채택 WHERE 조건**(혼합): `id_overlap_count > 0 OR name_overlap_count > 0 OR (profile_vector_score >= $vector_threshold AND cu.principle <> '제재')` (`retriever.py:198-203`). 즉 hypernym overlap이 있거나, 또는 벡터 유사도가 임계(`ACTIONABLE_VECTOR_THRESHOLD = 0.68`, `retriever.py:24`) 이상이면서 제재 CU가 아니면 후보로 들어온다.
- **DB 정렬**: `0.55*profile_vector_score + 0.35*(overlap/seed크기) + 0.10` (`retriever.py:256-262`).
- **Python 재계산 점수**: `candidate_from_row`에서 `id_overlap`/`name_overlap`을 비율로 다시 구하고(`retriever.py:350-352`), `combined_score = 0.40*vector + 0.25*overlap + 0.25*legal_element + 0.10*active` (`retriever.py:362`, 재계산은 `with_legal_element_gate` `retriever.py:441-446`). `retrieval_basis`는 overlap>0이면 `"hypernym_overlap"`, 아니면 `"embedding_profile"` (`retriever.py:363`).
- 순수 코사인 fallback 함수 `cosine()`(`retriever.py:394-402`)는 DB가 `profile_vector_score`를 안 줄 때만 사용(`retriever.py:347`).

### 임베딩 모델 및 대상

- 모델: `OPENAI_EMBEDDING_MODEL` 환경변수, 기본값 `"text-embedding-3-small"` (`ccg_embeddings.py:15`). 클라우드 OpenAI 전용이며 로컬/결정론적 fallback이 명시적으로 없음 — 키 없으면 즉시 실패 (`ccg_embeddings.py:1-5, 20-21`). 호출은 `EmbeddingGateway.embed/embed_many -> client.embeddings.create` (`ccg_embeddings.py:25-32`).
- 임베딩 **대상**:
  - 질의측: 앵커 텍스트(span.text + facts + hypernym why)를 합쳐 임베딩 (`anchor_embedding`, `retriever.py:161-168`); `policy_context_for_claims`에서는 query_text (`retriever.py:108`).
  - 인덱스측: `CUEmbeddingProfile.embedding`(CU 프로파일 텍스트, `retriever.py:178-188`)과 `Premise.embedding`(유사 정책 단편 검색, `retriever.py:314-316`, `_similar_policy_fragments`). LegalChunk/LegalClause는 메인 후보 엔진이 아니라 증거/근거 창 용도 (`retriever.py:1-10`).
  - 불확실: legal-element profile(`CULegalElementProfile`) 자체에는 임베딩이 없음 — 코드상 임베딩 유사도가 아니라 feature 집합 교집합으로만 매칭됨(아래 게이팅 참조).

### 게이팅 단계: 후보를 자르는 방식

Python 단계에서 3종 게이트가 순차 적용(`retriever.py:280-287`):

1. **scope gate** (`with_scope_gate`, `retriever.py:458-481`): 상품군/채널 적용범위 불일치 시 `gate_status="suppressed"`. 상품 텍스트 토큰 불일치(`is_product_scope_mismatch`, `retriever.py:556-574`) 또는 profile의 `applicability_scope` 토큰 불일치(`profile_scope_mismatch_reason`, `retriever.py:517-541`).
2. **legal-element gate** (`with_legal_element_gate`, `retriever.py:421-455` -> `candidate_satisfies_legal_elements`, `legal_elements.py:280-303`): **positive claim evidence 요건**의 핵심. 앵커의 `feature_set.positive_features`/`action_types`와 CU의 `CULegalElementProfile.required_positive_features`/`action_type`를 대조.
   - profile 없으면 탈락: `missing_cu_legal_element_profile` (`legal_elements.py:285-286`).
   - `action_type`이 `review_procedure`/`sanction_only`면 비-actionable로 탈락 (`legal_elements.py:287-288`).
   - CU의 action_type이 앵커 action_types에 없고 required feature가 있으면 탈락 (`legal_elements.py:291-292`).
   - 필수 positive feature 집합이 앵커 feature와 교집합 0이면 탈락(필수 요소 전부 미충족, `legal_elements.py:293-296`). `comparison_ad`/`unfair_superior_position_sales`는 추가 강제 교집합 요건 (`legal_elements.py:297-302`).
3. **최종 허용 필터** (`candidate_allowed_for_anchor`, `retriever.py:405-418`): suppressed 제외, operational(제재/심의/절차) 제외(`is_operational_candidate`, `retriever.py:577-599`), `legal_element_match=False` 제외, `product_anchor`/`target_consumer_anchor` 앵커 제외. overlap=0이면서 `principle=='제재'`면 제외; 그 외엔 `vector_score >= 0.68`이라야 통과.

**CUPlan 0/탈락 -> risk_code 연결**: `build_retrieval_diagnostics`(`workflow.py:541-575`)가 앵커별 `failure_code`를 산출 — CUPlan 포함 시 `MATCHED`, hypernym 없으면 `NO_HYPERNYM_MATCH`, 후보 0이며 action_types 있으면 `NO_LEGAL_ELEMENT_MATCH`(없으면 `MISSING_POLICY_COVERAGE`), active CU 없으면 `NO_ACTIVE_CU_AFTER_GATE`, 그 외 `RERANK_DROPPED_ALL` (`workflow.py:551-560`). 이 코드는 `system_review_items_for`에서 `risk_code`로 직결되며 기본 fallback은 `CU_PLAN_EMPTY` (`router.py:435-447`). 각 코드의 한국어 설명/조치는 `retrieval_failure_rationale`/`_action` (`router.py:451-468`). 단, actionable 앵커가 CUPlan 0이 되지 않도록 `ensure_actionable_anchors_have_plan_items`가 legal-element 매칭된 최고 combined_score 후보 1개를 강제 보존(`planner.py:135-171`).

### 리랭킹: cross-encoder vs LLM 순서

- **순서**: 1차 graph 검색 -> **cross-encoder rerank** -> **LLM rerank**. cross-encoder가 LLM 앞단 (`workflow.py:304-350`; `cross_encoder_reranker.py:1-6`).
- **cross-encoder**(옵션): `create_cross_encoder_reranker_from_env`가 `CCG_ENABLE_CROSS_ENCODER_RERANKER`를 읽어 `{1,true,yes,y}`일 때만 `FlagEmbeddingCrossEncoderCUReranker`, 아니면 `NoopCUReranker`(비활성) (`cross_encoder_reranker.py:106-112`). 모델 기본값 `BAAI/bge-reranker-v2-m3` (`DEFAULT_MODEL`, `cross_encoder_reranker.py:18`; override `CCG_CROSS_ENCODER_RERANKER_MODEL`). `FlagEmbedding` 미설치 시 RuntimeError (`cross_encoder_reranker.py:55-61`). 점수: `anchor_packet`/`candidate_packet` 쌍을 `compute_score(normalize=True)`로 채점(`cross_encoder_reranker.py:90-93`), 결합점수 `0.60*ce + 0.20*legal_element + 0.15*hypernym + 0.05*scope`이되 `legal_element_match=False`면 0 (`cross_encoder_reranker.py:115-122`). 활성 시 앵커당 8개로 절단(`workflow.py:314`, `cross_encoder_reranker.py:102`).
- **LLM rerank**: `LLMCUPlanner.plan`이 `llm.structured(name="graphcompliance_cuplan_rerank", ...)`로 항상 실행(`planner.py:78-103`). 시스템 프롬프트가 "cross-encoder-style reranker"로 동작하며 이미 retrieve/legal-eligible된 집합만 확정 (`planner.py:81-98`). 앵커당 ≤5, 총 ≤20 선택 (`planner.py:100-121`). 즉 cross-encoder는 옵션·비활성 가능, LLM rerank는 상시.

### 언어 의존(한국어 토큰) 위치 요약

이 파이프라인의 한국어 토큰 의존은 임베딩 코사인 구간이 아니라 **규칙기반 토큰 매칭 구간**에 집중된다: 앵커 feature 추출(`context_features_from_text` 한국어 토큰, `applicability_gate.py:46-61`; `build_anchor_feature_set`의 해시태그식 한글 토큰 검사, `legal_elements.py:178-207`), CU 텍스트 기반 action_type/feature/risk_title 추론(`ACTION_TYPE_BY_PROFILE_TEXT`·`FEATURE_ALIAS_RULES`, `legal_elements.py:80-156`), 상품/채널 scope 별칭과 토큰 매칭(`PRODUCT_SCOPE_ALIASES`/`CHANNEL_SCOPE_ALIASES`/`is_product_scope_mismatch`, `retriever.py:484-574`), operational 제재어 필터(`is_operational_candidate`, `retriever.py:578-599`), `principle=='제재'` 하드코딩(`retriever.py:202, 416`). 반면 벡터 유사도(`text-embedding-3-small`)와 hypernym id/name 집합 교집합은 다국어 모델·식별자 기반이라 토큰 사전에 직접 의존하지 않는다. 결과적으로 한국어 사전·정규식이 누락되면 legal-element/scope 게이트가 잘못 닫혀(positive feature 미검출) 정상 후보가 `NO_LEGAL_ELEMENT_MATCH`로 탈락하는 언어 의존적 실패 지점이 된다.

[읽은 파일 절대경로]
- /Users/kunwoo/Desktop/workspace/junbub/repo/retriever.py
- /Users/kunwoo/Desktop/workspace/junbub/repo/retrieval_probe.py
- /Users/kunwoo/Desktop/workspace/junbub/repo/cross_encoder_reranker.py
- /Users/kunwoo/Desktop/workspace/junbub/repo/ccg_embeddings.py
- /Users/kunwoo/Desktop/workspace/junbub/repo/applicability_gate.py
- /Users/kunwoo/Desktop/workspace/junbub/repo/legal_elements.py (게이팅 근거 확인용)
- /Users/kunwoo/Desktop/workspace/junbub/repo/planner.py, workflow.py, router.py (파이프라인 순서·risk_code 연결 확인용)

---

## 8. 관할/멀티-룰셋 개념 존재 여부

### 8.1 결론: 전용 관할/룰셋 파티션은 '없음'
코드 전체에 '여러 법령 세트(관할/국가/룰셋)를 구분해 다루는 장치'는 존재하지 않는다. 근거:
- 백엔드 `.py` 전체에서 `jurisdiction|ruleset|country|countries|locale` 단어의 매칭 건수는 **0건**(strict grep, `node_modules` 제외).
- `language`/`ko`/`Korean`은 다수 존재하나, 전부 "Korean financial-ad"라는 **고정 도메인 상수**로 프롬프트·설명에 하드코딩됨(예: `context_extractor.py:323` "You are a Korean financial-advertising context graph extractor", `legal_elements.py:1`, `vocabulary_governance.py:150-153`, `policy_compiler.py:402`). 즉 한국 관할이 코드·프롬프트에 박혀 있고, 관할을 데이터/파라미터로 분리하는 추상화가 없다.
- `build_synthetic_eval_dataset.py:583,630,672`의 `"language": "ko"`와 `evaluate.py:54 language: str = "ko"`는 평가 레코드의 정적 필드일 뿐, 검색/게이팅에 관할 필터로 쓰이지 않음.
- `KR`/`KH`/`region`/`nation`을 식별자로 쓰는 곳은 백엔드에 없음. 프론트의 `KR` 매칭은 날짜 포맷 로케일(`HomeTab.tsx:34` `toLocaleString("ko-KR", …)`, `useReview.ts:59`)뿐.
- 캄보디아/khmer 관련 코드/데이터는 전무.

### 8.2 workspace_id = 사실상 유일한 파티션 키 (KH 분리의 1차 seam 후보)
`workspace_id`는 **모든 노드의 식별 키이자 모든 Cypher MATCH/MERGE의 필수 필터**로 일관되게 붙는다 — 이 시스템의 유일한 파티션 메커니즘이다.
- 기본값: `graphcompliance_mvp_jb_20260530` (백엔드 `jb_data_context.py:475`, `schemas.py:40`, `load_product_graph.py:28`, `run_store.py:32`; 프론트 `frontend/src/lib/labels.ts:3`). 환경변수 `WORKSPACE_ID`/`GRAPHCOMPLIANCE_WORKSPACE_ID`/`CCG_WORKSPACE_ID`로 오버라이드 가능.
- 노드/관계 전 구간에 키로 부착: 광고·런(`persistence.py:53-57`), 클레임 그래프 체인(`persistence.py:104-118`), CU 플랜·증거·판정(`persistence.py:364-440`), 정책 그래프(`policy_compiler.py:527,537`), 제품 그래프(`load_product_graph.py:222,234,246,261`), 법령 계층(`legal_hierarchy.py:29`).
- 검색·게이팅 쿼리도 전부 `{workspace_id: $workspace_id}`로 스코프됨: `retriever.py:78,83,86,114,131,174,178,181,207`, `applicability_gate.py`, `bridge_exception_rules.py:78`.

평가: `workspace_id`는 그래프를 완전 격리하므로, 캄보디아 룰셋을 **별도 workspace_id(예: 새 KH 전용 ID)** 로 적재하면 데이터 레벨에서 KR/KH가 즉시 분리된다. 가장 비용이 낮은 seam이다. 다만 한계가 있다 — (a) 한 요청은 단일 `workspace_id`만 받으므로(서버 `server.py:78,144`가 payload에서 1개만 추출) "여러 관할을 동시에 비교/병합"하는 멀티-룰셋 질의는 불가, (b) 프롬프트의 "Korean" 하드코딩은 workspace를 바꿔도 그대로 남아 KH 데이터에 한국어 가정이 새어든다. 따라서 workspace_id는 **데이터 격리 seam은 되지만 관할-인식(jurisdiction-aware) 로직 seam은 아니다.**

### 8.3 관할 태깅을 추가할 자연스러운 위치 (현재 없음 → 추가 필요)
CU/Premise/PolicyHypernym에 관할 프로퍼티(예: `jurisdiction: 'KR'|'KH'`)를 붙이려면, 노드 생성 함수에 프로퍼티를 추가해야 한다. 현재 이들 노드의 쓰기 지점:
- **PolicyHypernym**: `policy_compiler.py:527-528` `MERGE (h:PolicyHypernym {id, workspace_id}) SET h += row …` → `row`에 `jurisdiction`을 채워 넣거나 `SET h.jurisdiction = $jurisdiction` 추가.
- **Premise**: `policy_compiler.py:537-538` `MERGE (p:Premise {id, workspace_id}) SET p += $props …` → `props`(premise dict)에 `jurisdiction` 필드 추가.
- **CULegalElementProfile(=CU의 관할 태깅 후보)**: ComplianceUnit 노드 자체는 이 평면 `.py`들에서 **생성되지 않고 MATCH만 됨**(`retriever.py:178`, `policy_compiler.py:556,573`; CU 소스는 외부 적재로 `policy_compiler.py:178` "No active ComplianceUnit sources found"가 확인). 따라서 CU에 관할을 태깅할 가장 가까운 **코드상 위치는 CU의 법적 프로파일 생성 함수** `legal_elements.py:236-257` `build_legal_element_profile_from_compiler_row(...)`의 반환 dict — 여기 `applicability_scope`(`legal_elements.py:240,252`) 옆에 `jurisdiction`을 추가하는 것이 자연스럽다. CU 본체 노드에 직접 태깅하려면 외부 CU 적재기(이 repo 평면 파일에 부재, 불확실)를 수정해야 한다.
- 참고: `applicability_scope`(product_group/channel 수준 스코프)가 **유일하게 존재하는 "scope" 추상화**다(`schemas.py:31`, `legal_elements.py:240`, `retriever.py:251,521`, `policy_compiler.py:118-127`). 관할은 이 토큰 집합에 끼워넣기보다 별도 차원으로 분리하는 편이 안전하다(현재 스코프는 제품군/채널 의미로만 정규화됨 — `retriever.py:513-541 profile_scope_mismatch_reason`).

### 8.4 관할 필터를 넣어야 할 검색/게이팅 위치 (현재 없음 → 추가 필요)
요청의 관할을 받아 후보를 걸러내려면 다음 지점에 `AND cu.jurisdiction = $jurisdiction`(또는 profile 레벨) 절을 추가해야 한다. 현재 이 절들은 없다:
- **CU 후보 검색 메인 쿼리**: `retriever.py:178-181` (`MATCH (cu:ComplianceUnit {workspace_id})-[:HAS_EMBEDDING_PROFILE]->(profile) WHERE cu.active_for_gate = true …`) — 여기 WHERE에 관할 절 추가가 가장 핵심.
- **법적 프로파일 조인**: `retriever.py:207` (`OPTIONAL MATCH (cu)-[:HAS_LEGAL_ELEMENT_PROFILE]->(legal_profile:CULegalElementProfile {workspace_id})`) — 관할을 profile에 둔 경우 이 매치에 `{jurisdiction: $jurisdiction}` 추가.
- **시드 PolicyHypernym 매치**: `retriever.py:174-175` 및 다른 retriever 변형 `retriever.py:78,83,86,114,131`.
- **애플리케이션 레벨 게이트 함수**: `retriever.py:458 with_scope_gate(...)` / `applicability_gate.py:64 gate_disclosure_catalog(...)` — 여기 관할 불일치 시 `gate_status="suppressed"`를 추가하는 형태로 후처리 게이팅도 가능(쿼리 수정 없이 파이썬 레벨에서 거를 수 있는 보조 seam).
- **요청 진입점**: `candidates_for_anchor(...)` 시그니처(`retriever.py:34`, `retriever.py:149-157`)에 `jurisdiction: str` 파라미터를 추가하고, 호출자인 `workflow.py`/`server.py:78,144`까지 전파해야 한다(현재 `product_group`, `channel`만 전파됨 — 동일 경로를 그대로 따라가면 됨).

### 8.5 불확실 사항
- **불확실**: ComplianceUnit/법령 원천 노드의 **실제 적재 코드**(CU 본체에 프로퍼티를 박는 곳)는 이 repo 루트 평면 `.py`들에 보이지 않는다(`policy_compiler.py:178`이 외부 적재를 전제로 "active ComplianceUnit sources"를 MATCH만 함). CU 노드 자체에 `jurisdiction`을 직접 태깅하려면 그 외부 적재기/시드 데이터 위치를 추가 확인해야 한다. `data/` 디렉터리 및 별도 ETL은 본 섹션 범위에서 정밀 확인하지 못함.
- **불확실**: `data/ontology.yaml`(`data/ontology.yaml:3` "Korean financial-ad pre-review")·`financial-compliance-ad-review.yaml`의 스키마에 관할 차원을 추가할 여지가 있으나, 이들 스키마 파일 전체 정밀 검토는 본 섹션에서 수행하지 않음.

---

## 9. DisclosureRequirement(필수 고지) 카탈로그

### 9.1 두 갈래의 disc/disclosure 데이터 — 핵심 주의점

저장소에는 **이름이 비슷하지만 출처가 다른** 두 종류의 고지 데이터가 있다. 혼동 주의:

1. **그래프 정제 카탈로그 (`disc_*`, source=`agentic_policy_inventory`)** — 적용범위(어느 상품군에 필요한가)를 데이터로 보유. `DisclosureRequirement {id: 'disc_*', label, product_groups: [...]}` 형태. 조회는 `disclosure_catalog.py:disclosure_catalog_for_group()` (`:350-412`). 이 노드의 적재 스크립트는 본 저장소 .py에 **없음**(불확실: 외부 inventory 파이프라인 산출). `disclosure_catalog.py:1-13` docstring이 이를 명시.
2. **코드 내장 프로파일 (`DISCLOSURE_PROFILES`, `disc_*` 동일 id 규약)** — 토큰·조문·검사방식을 코드로 보유. `disclosure_catalog.py:76-259`. 17개 항목(아래 9.3).
3. **레거시 하드코딩 요건 (`disclosure_*`, source=`graphcompliance_ccg_product_graph_loader`)** — `jb_data_context.py:26-107`의 `DISCLOSURE_REQUIREMENTS` dict. 이것이 `load_product_graph.py:275-287 write_disclosure_requirements()`로 `DisclosureRequirement {id:'disclosure_*'}` 노드를 적재하고, 런타임에도 `build_product_context()`→`requirements_for_group()`(`jb_data_context.py:147-155`)로 산출돼 `ReviewRun`/`ProductGroup`에 연결(`persistence.py:485-501`). **즉 적재기가 만드는 노드 id는 `disclosure_*`이고, 조회기가 찾는 id는 `disc_*`로 서로 접두가 다르다.**

### 9.2 `disc_*` 노드 구성·적재·런타임 조회/매칭 경로

- **id 규약**: 모두 `disc_` 접두 (`disclosure_catalog.py:77` 등 `DISCLOSURE_PROFILES` 키). 적용범위 노드는 추가로 `product_groups` 배열과 `source='agentic_policy_inventory'`를 가져야 조회됨.
- **상품군 토큰 매핑**: 앱 상품군→그래프 토큰 변환 `PRODUCT_GROUP_TO_GRAPH = {"deposit":"deposit","loan":"loan","investment":"investment_fund"}` (`disclosure_catalog.py:23-27`). 즉 그래프에서 투자상품은 `investment_fund`로 저장됨.
- **그래프 조회 함수** `disclosure_catalog_for_group(workspace_id, product_group)` (`disclosure_catalog.py:350-412`):
  - Cypher: `MATCH (req:DisclosureRequirement {workspace_id}) WHERE req.source='agentic_policy_inventory' AND $group IN req.product_groups RETURN req.id, req.label ORDER BY req.id` (`:373-381`).
  - 각 행의 `disc_id`에 대해 `disclosure_profile_dict()`(`:272-276`)로 코드 프로파일을 입힘(토큰·조문 보강). 프로파일이 없으면 `profile_supported=False`, `check_type='unsupported'` 행으로 채움 (`:386-407`).
  - Neo4j 자격증명 없거나 그룹 미매핑이면 `None` 반환 → 호출부 폴백 (`:358-367`, `_neo4j_config()` `:341-347`). `@lru_cache(maxsize=32)` (`:350`).
- **런타임 매칭 산출 경로** `product_facts.py:build_disclosure_checks()` (`:424-507`):
  1. `product_group=='auto'`면 광고 텍스트 토큰으로 그룹 추정 (`:438-445`).
  2. `disclosure_catalog_for_group(...)`(그래프) 결과를 `merge_profile_and_graph_catalog(profile_catalog_all(), graph_catalog)`로 코드 프로파일 전체와 병합 (`:448-449`, 병합 로직 `:510-523`). 병합 키는 `check_id`; 그래프 행은 label만 덮어쓰고, 코드에 없는 disc는 그래프 행 그대로 추가.
  3. `applicability_gate.gate_disclosure_catalog()`로 상품군/채널 게이트(enabled/skipped) 분리 (`:451`).
  4. enabled 항목은 `build_profile_disclosure_check()`(`:597-655`)로 판정: `any_token(text, detect_tokens)` 양성/`negative_tokens` 부정, `required_roles`가 SentenceUnit.role에 존재하는지(`sentence_role_present` `:678-681`), `link_disclosure_to_facts()`로 상품문서 product_fact 근거 연결(`:722-752`). 최종 상태는 `disclosure_status()`(`:658-675`)가 `PRESENT/PRESENT_BUT_NEGATED/IN_PRODUCT_DOC_ONLY/NOT_TESTED/MISSING` 중 결정.
  5. skipped 항목은 `build_skipped_disclosure_check()`로 `status='SKIPPED_BY_GATE', gate_status='OFF'` (`:684-701`).
  6. 카탈로그가 비면(그래프·프로파일 모두 없음) `product_group`별 **하드코딩 폴백** 체크리스트로 분기 (`:472-507`: deposit/loan/investment), `disclosure_check()`(`:560-572`)는 순수 토큰 존재만 판정.
- **누락 판정**: `run_store._summary()` (`:92-98`)에서 `gate_status=='ON'` 이면서 `not present`인 체크의 label만 `missing_disclosures`로 집계.

### 9.3 코드 내장 카탈로그 전수 (`DISCLOSURE_PROFILES`, disclosure_catalog.py:76-259)

| check_id (disc_*) | check_type | on_missing | severity | product_groups | source(근거) | 라인 |
|---|---|---|---|---|---|---|
| `disc_interest_condition` | presence_and_prominence | revise | 3 | deposit | 은행 광고심의 기준 제16조·제18조 | `:77` |
| `disc_depositor_protection_notice` | presence | needs_review | 2 | deposit | 은행 광고심의 기준 제16조 | `:90` |
| `disc_tax_and_after_tax_notice` | fact_match | needs_review | 2 | deposit | 은행 광고심의 기준(세전/세후) | `:102` |
| `disc_variable_rate_notice` | presence_and_prominence | revise | 3 | deposit, loan, investment | 금융소비자보호법 광고규제 | `:112` |
| `disc_product_terms_notice` | presence | needs_review | 2 | deposit, loan, investment | 금융소비자보호법 제19조 | `:124` |
| `disc_review_approval_notice` | review_procedure | needs_review | 1 | deposit, loan, investment | 은행 광고심의 기준 제4조·제9조 | `:134` |
| `disc_seller_name` | presence | needs_review | 1 | deposit, loan, investment | 금소법 광고규제(판매업자 명칭) | `:144` |
| `disc_economic_interest_notice` | presence | needs_review | 2 | deposit, loan, investment (channels: sns, youtube) | 금소법 광고규제(추천·보증 이해관계) | `:153` |
| `disc_direct_seller_confirmation` | presence | needs_review | 2 | deposit, loan, investment (channels: sns, youtube) | 금소법 광고규제(직접판매업자 확인) | `:163` |
| `disc_loan_conditions` | presence_and_prominence | revise | 3 | loan | 은행 광고심의 기준(대출 대상·자격·담보) | `:173` |
| `disc_overdue_interest_rate` | fact_match | revise | 3 | loan | 은행 광고심의 기준(연체이자율) | `:185` |
| `disc_early_repayment_fee` | fact_match | needs_review | 2 | loan | 은행 광고심의 기준(중도상환수수료) | `:195` |
| `disc_credit_score_impact` | presence | needs_review | 2 | loan | 신용정보법/금소법(신용평점 영향) | `:205` |
| `disc_principal_loss_notice` | presence_and_prominence | **reject** | 3 | investment | 자본시장법 제57조(원금손실) | `:214` |
| `disc_past_performance_disclaimer` | presence_and_prominence | revise | 3 | investment | 금융투자회사 영업·업무규정(과거실적 비보장) | `:227` |
| `disc_risk_grade` | fact_match | revise | 3 | investment | 금융투자상품 위험등급 표시 기준 | `:239` |
| `disc_fee_notice` | fact_match | needs_review | 2 | loan, investment | 자본시장법(수수료·보수) | `:249` |

각 프로파일 필드: `detect_tokens / negative_tokens / fact_match_tokens / required_roles / prominence_required / channels` (`DisclosureRequirementProfile` `disclosure_catalog.py:29-42`, 기본값 채움 `profile()` `:45-73`). 사람용 라벨은 `readable_label()` (`:318-338`). 상품군별 코드 카탈로그 추출은 `profile_catalog_for_group()` (`:297-306`, `PRODUCT_GROUP_TO_GRAPH`로 그룹 정규화 후 매칭), 전체는 `profile_catalog_all()` (`:309-315`). 하위호환 별칭 `DISC_ENRICHMENT: {check_id: (detect_tokens, source)}` (`:262-265`).

불확실: `disc_*` `agentic_policy_inventory` 노드 자체의 적재 코드는 본 저장소 .py에 존재하지 않아(grep로 `MERGE/CREATE` 생성 0건; `DisclosureRequirement` 생성은 `disclosure_*` id를 쓰는 `load_product_graph.py:279`뿐), 그래프 카탈로그의 권위 있는 정의·적재는 외부 inventory 파이프라인에 있다.

---

## 10. 로컬/클라우드 LLM 토글 & json_schema 강제

### 10.1 LLMGateway 구조 — 두 경로의 분기 (llm_gateway.py)

`LLMGateway` 는 생성 시점에 `self.mode` 를 `"responses"`(클라우드) 또는 `"chat"`(로컬)로 고정하고, 이후 모든 호출이 그 모드를 따른다. 분기는 전적으로 `__init__()`(`llm_gateway.py:52`)에서 결정된다.

분기 우선순위(위에서부터 먼저 매칭):
1. `client` 주입 시(테스트/커스텀): 무조건 `mode="responses"`, 모델은 `requested or OPENAI_MODEL or DEFAULT_MODEL`(`llm_gateway.py:73-77`).
2. 요청 모델이 로컬 태그집합에 속하면(`requested in LOCAL_MODELS`): `_make_local(requested)` 호출로 로컬 경로(`llm_gateway.py:78-80`). `LOCAL_MODELS = {"ax-4.0-light", "midm-2.0-base", "exaone4-32b", "qwen3.5:9b", "gemma4"}`(`llm_gateway.py:32`).
3. 전역 로컬 토글 `LLM_BASE_URL` 가 설정돼 있으면(`global_local`): 모든 요청을 로컬로 보내고, 모델은 `requested or LLM_MODEL or DEFAULT_LOCAL_MODEL`(="ax-4.0-light")(`llm_gateway.py:81-83`, `27`).
4. 그 외(클라우드 기본): `OPENAI_API_KEY` 없으면 즉시 `RuntimeError`(폴백 없음, fail-fast)(`llm_gateway.py:85-89`). 있으면 `OpenAI(timeout=..., max_retries=...)` 로 `mode="responses"`, 모델은 `requested or OPENAI_MODEL or DEFAULT_MODEL`(="gpt-5.4-nano")(`llm_gateway.py:93-95`, `26`).

로컬 클라이언트 구성 `_make_local()`(`llm_gateway.py:57-71`):
- base_url 우선순위: `LOCAL_LLM_BASE_URL` → `LLM_BASE_URL`(`_local_base_url()`, `llm_gateway.py:43-44`). 둘 다 없으면 "로컬 모델인데 엔드포인트 미설정" `RuntimeError`(`llm_gateway.py:58-62`).
- api_key 우선순위: `LOCAL_LLM_API_KEY` → `LLM_API_KEY` → 리터럴 `"ollama"`(`_local_api_key()`, `llm_gateway.py:47-48`).
- 결과: `OpenAI(base_url=local_base, api_key=..., timeout=..., max_retries=...)`, `self.mode = "chat"`(`llm_gateway.py:63-70`).

즉 라우팅 키:
- `LLM_BASE_URL` → 전역 로컬 토글(모든 요청 로컬) + 로컬 base_url 후보.
- `LOCAL_LLM_BASE_URL` → 로컬 base_url 우선후보(단, 이것만으로는 전역 토글이 켜지지 않음 — 전역 토글 조건은 `LLM_BASE_URL` 만 검사, `llm_gateway.py:54`). 불확실 측면 명시: `LOCAL_LLM_BASE_URL` 만 설정하고 `LLM_BASE_URL` 미설정 시, 클라우드 기본 모드가 되며 로컬 태그 모델을 명시 선택했을 때만 로컬 경로가 동작함(`llm_gateway.py:78-84`).
- `LLM_API_KEY`/`LOCAL_LLM_API_KEY` → 로컬 인증(Ollama 등은 무의미값 허용, 기본 `"ollama"`).
- `LLM_MODEL` → 전역 로컬 토글 시 기본 모델, `OPENAI_MODEL` → 클라우드 기본 모델.
- 모델 태그(예: `ax-4.0-light`) → `LOCAL_MODELS` 매칭으로 provider 자체를 로컬로 전환(클라우드 기본 모드에서도).

타임아웃/재시도는 env로 제어: `CCG_OPENAI_TIMEOUT_SECONDS`(기본 120), `CCG_OPENAI_MAX_RETRIES`(기본 1)(`_timeout_seconds()` `llm_gateway.py:35-36`, `_max_retries()` `llm_gateway.py:39-40`).

### 10.2 요청별 모델 선택 — server.py workflow_for / payload.llm_model

`workflow_for(payload)`(`server.py:37-46`):
- `model = str(payload.get("llm_model") or "").strip()`(`server.py:43`).
- `model` 이 비어있지 않으면 `GraphComplianceCCGWorkflow(llm=LLMGateway(model=model))` — 즉 요청 페이로드의 `llm_model` 이 게이트웨이 생성자의 `model` 인자로 전달돼 §10.1의 분기 2(로컬 태그면 로컬)/분기 4(아니면 클라우드)에 따라 경로가 정해진다(`server.py:44-45`).
- `model` 이 비어있으면 `GraphComplianceCCGWorkflow()` — 인자 없는 기본 `LLMGateway()` 생성(클라우드↔로컬은 순수 .env가 결정)(`server.py:46`).

오버라이드 성격: docstring(`server.py:38-42`)대로 클라우드↔로컬 "provider" 전환의 큰 틀은 .env(`LLM_BASE_URL`)가 정하고, `payload.llm_model` 은 활성 경로 안에서 "모델만" 오버라이드한다. 단 예외적으로 `llm_model` 값이 `LOCAL_MODELS` 태그이면 .env가 전역 로컬 토글을 켜지 않은 클라우드 기본 모드라도 그 요청만 로컬 provider로 넘어간다(`llm_gateway.py:78-80`). `workflow_for` 는 `/api/...` 동기 경로(`server.py:64`)와 스트리밍/비동기 경로(`server.py:124`) 양쪽에서 호출되고, 동일 `llm_model` 값이 `ReviewInput.model`(또는 그에 상응하는 `model=` 인자)로도 함께 전달된다(`server.py:75`, `141`).

OpenAI 거절 시 사용자 메시지: "Check OPENAI_MODEL and structured-output support."(`server.py:105`, `292`) — 구조화 출력 비지원 모델 선택에 대한 진단 힌트.

### 10.3 구조화 출력 강제 — json_schema 설정 위치

단일 진입점은 `LLMGateway.structured()`(`llm_gateway.py:97-171`)이며 `self.mode` 에 따라 두 경로로 갈린다.

클라우드 경로(`mode != "chat"`, 즉 "responses")(`llm_gateway.py:122-146`):
- `client.responses.create(...)` 호출(`llm_gateway.py:123`).
- 구조화 강제: `text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}}`(`llm_gateway.py:129-136`). OpenAI Responses API의 strict json_schema structured output.
- `status == "incomplete"` 면 `RuntimeError`(`llm_gateway.py:140-141`), content `type == "refusal"` 면 `RuntimeError`(`llm_gateway.py:142-145`). 최종 텍스트는 `response.output_text`(`llm_gateway.py:146`).

로컬 경로(`mode == "chat"`)(`llm_gateway.py:118-119` → `_chat_structured()` `llm_gateway.py:173-216`):
- 1차: `client.chat.completions.create(...)` 에 `response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}`, `temperature=0`(`llm_gateway.py:191-199`). 즉 로컬(OpenAI 호환 Chat Completions/Ollama) 경로의 `response_format=json_schema` 강제는 여기서 설정됨.
- 폴백: 엔드포인트가 json_schema 미지원으로 `BadRequestError` 던지면(`llm_gateway.py:200`), system 프롬프트에 JSON Schema를 직접 주입(`json.dumps(schema)`)하고 `response_format={"type": "json_object"}` 로 재호출(`llm_gateway.py:201-214`). 모듈 docstring(`llm_gateway.py:9-12`)이 설명하는 "Ollama는 /v1/chat/completions만 지원하므로 스키마를 프롬프트에 주입" 경로가 이 폴백에 해당.
- 응답 텍스트는 `response.choices[0].message.content` 에 `_strip_json_fence()`(```json 펜스 제거, `llm_gateway.py:219-227`) 적용(`llm_gateway.py:215-216`).

양 경로 공통: 반환 직전 `json.loads(output_text)` 로 파싱(`llm_gateway.py:157`).

### 10.4 스키마 객체 정의 위치 — schemas.py 연결

중요 사실: `structured(schema=...)` 에 넘기는 JSON Schema dict(`*_SCHEMA`)들은 **schemas.py 가 아니라 각 에이전트 모듈에 인라인 정의**되어 있다. schemas.py 는 dataclass 타입 계약(`ReviewInput`, `Claim`, `ContextAnchor`, `PolicyCandidate`, `LLMJudgment` 등)만 담고 있고(`schemas.py:1` 모듈 docstring "Typed contracts...", `schemas.py:5` `from dataclasses import dataclass`), JSON Schema dict 정의는 포함하지 않는다(루트 전역 grep에서 `*_SCHEMA = {`/`: dict` 정의는 schemas.py에 0건).

각 `*_SCHEMA` 정의 위치(`dict[str, Any]` 리터럴):
- `EXTRACTION_SCHEMA`(`context_extractor.py:30`), 같은 파일에서 `FRAME_SENTENCE_SCHEMA`/`CLAIM_CHUNK_SCHEMA`/`RELATION_INFLUENCE_SCHEMA` 도 사용(`context_extractor.py:321,380,411`).
- `OVERALL_IMPRESSION_SCHEMA`(`overall_impression.py:12`, 사용 `:71`).
- `JUDGE_SCHEMA`(`judge.py:33`, 사용 `:200`), `EXCEPTION_SCHEMA`(사용 `judge.py:297`).
- `REVISION_SCHEMA`(`revision.py:243`, 사용 `:330`).
- `RERANK_SCHEMA`(사용 `planner.py:80`), `PRODUCT_FACT_SCHEMA`/`CLAIM_FACT_COMPARISON_SCHEMA`(사용 `product_facts.py:265,314`), `GOVERNANCE_SCHEMA`(사용 `vocabulary_governance.py:148`), `COMPILER_SCHEMA`(사용 `policy_compiler.py:400`).
- `NORMALIZATION_SCHEMA`(`normalizer.py:18`) — 유일하게 동적 생성: `normalization_schema_for_allowed_ids()`(`normalizer.py:184-185`)가 `deepcopy(NORMALIZATION_SCHEMA)` 후 허용 id로 enum을 좁혀 반환하고, 그 결과가 `structured(schema=schema, ...)` 로 전달됨(`normalizer.py:81`, `110-112`).

json_schema의 `name` 인자는 각 호출부의 `name=` 문자열로 연결된다(예: `name="graphcompliance_cu_judgment"`, `judge.py:199`; `name="graphcompliance_policy_normalization"`, `normalizer.py:111`). 이 `name` 이 §10.3의 클라우드 `format.name`(`llm_gateway.py:132`)과 로컬 `json_schema.name`(`llm_gateway.py:197`)에 그대로 들어간다.

요약 연결: schemas.py = 파이썬 타입 계약(런타임 dataclass), 각 에이전트 모듈의 `*_SCHEMA` = LLM 구조화 출력용 JSON Schema. 둘은 의미적으로 대응하지만 코드상 자동 동기화/생성 관계는 확인되지 않음(불확실: `*_SCHEMA` 가 schemas.py dataclass로부터 파생/검증된다는 코드 근거 없음 — 수기 동기화로 보임).

---

## 11. Eval 하니스

### 위치와 실행 방법
- 하니스 본체: `evaluate.py`(클론 루트 `/Users/kunwoo/Desktop/workspace/junbub/repo/evaluate.py`). CLI 인자는 `main()` 의 argparse 정의에 있음: `--input`(필수, `evaluate.py:537`), `--predictions`(저장된 리뷰 출력 JSONL/JSON, `evaluate.py:538`), `--run-live`(라이브 CCG 워크플로 실행 후 평가, `evaluate.py:539`), `--output`(리포트 JSON 출력 경로, `evaluate.py:545`). 보조 인자: `--workspace-id`(기본 `graphcompliance_mvp_jb_20260530`, `evaluate.py:540`), `--workers`(라이브 병렬, `evaluate.py:541`), `--start`/`--limit`(배치 슬라이싱, `evaluate.py:542-543`), `--save-predictions`(라이브 예측 JSONL 저장, `evaluate.py:544`).
- 실행 분기: `--run-live` 면 라이브 예측을 만들고(`evaluate.py:553-561`), 아니면 `--predictions` 를 로드(`evaluate.py:562-563`); 둘 다 없으면 `raise SystemExit("--predictions or --run-live is required.")`(`evaluate.py:565`).
- 우리 클론 루트 기준 정적 채점(저장 예측) 커맨드 예시:
  - `python evaluate.py --input eval/smoke_financial_ad_review.jsonl --predictions <preds>.jsonl --output report.json`
  - 라이브: `python evaluate.py --input eval/synthetic_product_fact_100.jsonl --run-live --save-predictions preds.jsonl --output report.json` (라이브는 `workflow.GraphComplianceCCGWorkflow().review(...)` 를 import·호출 — `evaluate.py:467-468`, `481-487`. 정적 읽기 범위라 실행은 미검증).
- 출력: `evaluate_records(...)` 결과를 `json.dumps(..., indent=2)` 로 stdout 출력하고 `--output` 지정 시 동일 텍스트를 파일로 기록(`evaluate.py:567-572`).

### 데이터셋 (eval/ 디렉터리)
공통 레코드 스키마는 `record_from_json()`(`evaluate.py:76-97`)과 DATASET_CARD.md:28-47 에 정의. 골드 라벨 필드는 `labels.{violation, violation_types, articles, sales_principles, required_disclosures, risk_level, expected_routing, review_basis}`(`evaluate.py:87-96`)이며 `EvaluationLabels` dataclass(`evaluate.py:35-44`)로 매핑. 레코드 식별자는 `id`/`record_id`/`dataset_item_id` 중 우선순위로 해석(`evaluate.py:79`).

- smoke (`smoke_financial_ad_review.jsonl`, 6 레코드): 정상·위반 혼합 회귀/캘리브레이션 픽스처. precision·overblocking 측정용 균형 세트(DATASET_CARD.md:1-12, 94-95). 예: `id=smoke_deposit_clear_001`, `labels.violation=false`, `expected_routing=pass_candidate`. `facts` 는 "평가 문서화 전용, agent 프롬프트에 전달 안 됨"으로 명시(DATASET_CARD.md:33-34).
- redteam (`redteam_korean_financial_ad_12.jsonl`, 12 레코드): 준법 테스트용 DOCX에서 변환한 의도적 위반 과다(violation-heavy) recall/red-team 스위트, 균형 벤치마크 아님(DATASET_CARD.md:13-16, 63-69). 예: `id=A01`, `labels.violation=true`, `violation_types=[V03,V04,V05,V06,V12]`, `articles=[금소법 제19조/제21조/제22조]`, `risk_level=high`, `expected_routing=reject`. `facts.expected_problem_spans` 로 위반 구간 기록.
- synthetic_product_fact (`synthetic_product_fact_100.jsonl`, 100 레코드; 시드 `synthetic_product_fact_seed.jsonl` 3 레코드): `build_synthetic_eval_dataset.py` 가 실제 ProductFact 근거로 clean 광고 생성 후 taxonomy로 변이시켜 라벨/스팬을 변이 단계에서 확정(파이프라인 주석 `build_synthetic_eval_dataset.py:3-12`). 추가 필드 `structured_ad`, `source_type`(clean/mutation/hard_case), `facts.{product_name, source_product_documents, product_facts, clean_reference_text, mutation_code}`. `synthetic_product_fact_100_report.json` 기준 구성: clean 20 / mutation 60 / hard_case 20, routing pass_candidate 40·revise 40·reject 20, blocking_error_count 0. 변이 통제 코드는 `eval/violation_taxonomy_v0_1.json`(예 `DEPOSIT_RATE_CONDITION_MISSING`→`금소법 제22조`/`revise`, `RETURN_GUARANTEE_MISLEADING`→`reject`).

### 지표 계산
모든 지표는 `evaluate.py` 안에서만 계산됨. `judge.py` 에는 F1/F2/MCC/recall 계산 함수가 없음(`judge.py` 의 "evidence grounding"은 런타임 경고 `grounded_judgment_row()`/`evidence_span_belongs_to_anchor()`(judge.py:397-427)로 eval 지표와 무관).

- F1/F2(micro·macro)·MCC: `multilabel_metrics()`(`evaluate.py:204-244`). 조문(article)을 시나리오×라벨 평탄화 행렬로 펼쳐 article별 TP/FP/FN/TN 집계 후 `micro_f1/macro_f1/micro_f2/macro_f2`(`evaluate.py:233-240`)와 `mcc`(`evaluate.py:241`)를 반환. 보조: `fbeta(...)`(`evaluate.py:298-305`), `matthews_corrcoef(...)`(`evaluate.py:308-312`). 조문 정규화는 `canonical_article()`(`evaluate.py:369-378`, `LAW_ALIASES`/`ARTICLE_RE` 사용)로 통계명 별칭·조 단위 매칭.
- CCG 특화 지표: 전부 `ccg_metrics()`(`evaluate.py:247-295`)에서 계산.
  - `cuplan_recall`: 골드 조문이 있는 위험 레코드 중 예측 조문과 교집합이 있는 비율(`evaluate.py:253-257`, 273).
  - `evidence_grounding_rate`: 위반 예측 중 정책 근거 보유 비율(`evaluate.py:276-279`), 근거 판정은 `prediction_has_policy_evidence()`(`evaluate.py:315-322`, `used_policy_evidence`/`legal_evidence_ids`/`evidence_texts` 확인).
  - `cu0_rate`: 전체 중 CU0(검색 실패) 비율(`evaluate.py:280`), 판정 `prediction_has_cu0_failure()`(`evaluate.py:325-332`, `FAILURE_CODES` 집합 `evaluate.py:24-30`).
  - `overblocking_rate`: 정상 레코드 중 `final_verdict=="reject"` 비율(`evaluate.py:281-284`). 보조로 `clean_non_pass_rate`(pass_candidate 미진입 비율, `evaluate.py:286-289`).
  - `exception_sanity_rate`: 예금자보호 포함 정상 레코드 중 reject 아닌 비율(`evaluate.py:264-268`, 290-293).
  - `average_context_triples`: 레코드당 `context_triple_count` 평균(`evaluate.py:294`, 입력은 `summarize_prediction()` 의 `len(output.get("context_triples"))` — `evaluate.py:173`).
  - (참고) 위반 이진 분류 보조: `violation_precision`/`violation_recall`(`evaluate.py:274-275`).
- 예측 요약 추출: `summarize_prediction()`(`evaluate.py:115-176`)이 `cu_plan`·`effective_judgments`/`judgments`·`detected_issues`·`disclosure_requirements`·`final_verdict` 등 워크플로 출력에서만 필드를 뽑음. `predicted_violation` 은 `final_verdict in {"reject","revise"}` 로 정의하고 `needs_review` 는 위반으로 세지 않음(`evaluate.py:164-166`).

### 골드 라벨 누설 방지 장치 (코드 확인됨)
- 리뷰 입력 빌더 `review_payload_for_record()`(`evaluate.py:100-112`)는 docstring에 "deliberately excluding gold labels and fact values"라 명시하고, `labels` 와 `facts` 값을 페이로드에 넣지 않음. 페이로드는 `dataset_item_id/title/content_text/channel/source_type/product_group/selected_product_name/workspace_id` 만 포함(`evaluate.py:103-112`). `selected_product_name` 은 `facts.product_name` 한 항목만 선택 전달(`evaluate.py:108-110`) — 나머지 `facts`(product_facts/evidence 등)나 라벨은 차단.
- 라이브 경로(`run_live_predictions_sequential()` `evaluate.py:461-478`, `run_one_live_prediction()` `evaluate.py:481-487`)는 이 `review_payload_for_record(...)` 결과만 워크플로에 전달하므로 동일 차단이 적용됨.
- 골드 라벨은 `evaluate_records()`(`evaluate.py:179-201`)의 채점 단계에서만 읽혀 `gold` 블록으로 리포트에 기록됨(`evaluate.py:191-196`). 모듈 docstring(`evaluate.py:3-5`)과 DATASET_CARD.md:119-121("Gold labels are read only during evaluation. They must not be included in Context Graph extraction, CU retrieval, LLM judge, exception override, or revision-generation prompts.")가 동일 원칙을 명문화.
- 데이터셋 생성 측: `build_synthetic_eval_dataset.py:11-12` 도 "deliberately keeps gold labels out of the review workflow"라 명시.
- 불확실: 워크플로 내부(`workflow.py`/`judge.py`/Context Graph 추출 단계)가 `content_text` 외에 `facts`/`labels` 를 다른 경로로 재참조하지 않는지는 본 §11 범위 밖이며 정적으로 미검증. evaluate.py 단의 입력 차단은 확인됨.

---

## 12. 환경변수 & 비밀정보 점검

### 환경변수 키 전수(값 마스킹)

`.env.example`(루트) 선언 키: `OPENAI_API_KEY`(빈값), `OPENAI_MODEL=gpt-5.4-nano`, `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`, `LLM_BASE_URL`(빈값), `LLM_API_KEY=ollama`, `LLM_MODEL=ax-4.0-light`, `LOCAL_LLM_BASE_URL=http://mac-mini-m4-llm.tail023e97.ts.net:11434/v1`, `LOCAL_LLM_API_KEY=ollama`, `NEO4J_URI/USER/PASSWORD/DATABASE`(빈값), `CCG_ENABLE_CROSS_ENCODER_RERANKER=false`, `CCG_CROSS_ENCODER_RERANKER_MODEL=BAAI/bge-reranker-v2-m3`, `CCG_CROSS_ENCODER_USE_FP16=true` (`.env.example:1-31`).
`frontend/.env.example`: `LLM_BASE_URL=https://mac-mini-m4-llm.tail023e97.ts.net`, `LLM_API_KEY=<team-provided-key>`(플레이스홀더), 주석 `CCG_API_BASE=http://localhost:8770` (`frontend/.env.example:7-11`).

**코드에서 실제 참조되는 키와 위치·용도**(`os.environ`/`getenv`/`process.env` 전역 grep):

| 키 | 참조 위치(파일:라인) | 용도 |
|---|---|---|
| `OPENAI_API_KEY` | `llm_gateway.py:85`, `ccg_embeddings.py:20` | 클라우드 OpenAI 인증; 없으면 fail-fast |
| `OPENAI_MODEL` | `llm_gateway.py:77,95` | 클라우드 기본 모델(기본 `gpt-5.4-nano`) |
| `OPENAI_EMBEDDING_MODEL` | `ccg_embeddings.py:15` | 임베딩 모델 |
| `LLM_BASE_URL` | `llm_gateway.py:44,54,81`, `frontend/api/chat/route.ts:20` | 전역 로컬(Ollama) 토글/프록시 대상 |
| `LLM_API_KEY` | `llm_gateway.py:48`, `frontend/api/chat/route.ts:21` | 로컬/프록시 Bearer 키 |
| `LLM_MODEL` | `llm_gateway.py:83` | 전역 로컬 모드 기본 모델 |
| `LOCAL_LLM_BASE_URL` | `llm_gateway.py:44` | per-request 로컬 모델용 엔드포인트 |
| `LOCAL_LLM_API_KEY` | `llm_gateway.py:48` | per-request 로컬 키(기본 `ollama`) |
| `NEO4J_URI` | `persistence.py:26`, `jb_data_context.py:414,469`, `disclosure_catalog.py:342`, `load_product_graph.py:181`, `bridge_exception_rules.py:147`, `build_cross_law_citations.py:95` 외 | Neo4j 접속 |
| `NEO4J_USER` / `NEO4J_USERNAME` | `jb_data_context.py:414,470`, `disclosure_catalog.py:343`, `load_product_graph.py:182` 외 | Neo4j 사용자(USERNAME은 fallback) |
| `NEO4J_PASSWORD` | `jb_data_context.py:416,471`, `disclosure_catalog.py:344`, `bridge_exception_rules.py:149` 외 | Neo4j 비밀번호 |
| `NEO4J_DATABASE` | `jb_data_context.py:476`, `disclosure_catalog.py:347`, `bridge_exception_rules.py:73`, `load_product_graph.py:187` | Neo4j DB명 |
| `JB_PRODUCT_DISCLOSURE_ROOT` | `server.py:198,203`, `product_facts.py:793` | 상품설명서 PDF 루트(path-traversal 방어 기준) |
| `JB_PRODUCT_METADATA_PATH` | `jb_data_context.py:537` | 상품 메타 경로 |
| `JB_PRODUCT_DISCLOSURE_METADATA_PATH` | `product_facts.py:845` | 고지 메타 경로 |
| `WORKSPACE_ID` / `GRAPHCOMPLIANCE_WORKSPACE_ID` / `CCG_WORKSPACE_ID` | `jb_data_context.py:475`, `run_store.py:32` | 워크스페이스 식별(기본 `graphcompliance_mvp_jb_20260530`) |
| `CCG_RUNS_DIR` | `run_store.py:29` | 실행 스냅샷 저장 디렉터리(기본 `<repo>/runs`) |
| `CCG_LOG_LEVEL` | `server.py:30` | 로깅 레벨 |
| `CCG_REVIEW_STREAM_HEARTBEAT_SECONDS` | `server.py:120` | 스트림 heartbeat 간격 |
| `CCG_OPENAI_TIMEOUT_SECONDS` / `CCG_OPENAI_MAX_RETRIES` | `llm_gateway.py:36,40` | OpenAI 타임아웃/재시도 |
| `CCG_POLICY_NORMALIZATION_MODEL` / `..._TIMEOUT_SECONDS` | `normalizer.py:82` 외 | 정책 정규화 LLM 설정 |
| `CCG_CONTEXT_EXTRACTION_MODEL` / `..._STAGED` / `..._TIMEOUT_SECONDS` / `CCG_CONTEXT_CLAIM_CHUNK_SENTENCES` | `context_extractor.py:293` 외 | 맥락 추출 LLM 설정 |
| `CCG_ENABLE_CROSS_ENCODER_RERANKER` / `..._MODEL` / `CCG_CROSS_ENCODER_USE_FP16` | `cross_encoder_reranker.py`(1회씩 참조) | 선택적 재랭크 |
| `CCG_API_BASE` | `frontend/next.config.ts:3`, `frontend/src/app/api/review/stream/route.ts:3` | 프론트→FastAPI 프록시 대상(기본 `http://localhost:8770`) |
| `NEXT_PUBLIC_REVIEW_STREAM_STALL_WARNING_MS` / `..._HARD_ABORT_MS` | `frontend/src/hooks/useReview.ts:33,34` | 클라이언트 스트림 stall/abort 타이머(브라우저 노출 가능 `NEXT_PUBLIC_*`이나 값은 시간상수일 뿐) |

참고: 코드가 참조하지만 `.env.example`에 미선언된 키 존재 — `JB_PRODUCT_*`, `CCG_RUNS_DIR`, `WORKSPACE_ID`/`GRAPHCOMPLIANCE_WORKSPACE_ID`/`CCG_WORKSPACE_ID`, `CCG_OPENAI_*`, `CCG_POLICY_*`, `CCG_CONTEXT_*`, `CCG_API_BASE`, `NEXT_PUBLIC_*`. 모두 코드에 안전한 기본값이 있어 fail-fast 대상은 아님(예: `run_store.py:29`, `jb_data_context.py:475`).

### 커밋된 비밀정보 점검

- **tracked 파일 내 실제 키/비번: 없음.** tracked 파일 전체에 대한 패턴 스캔(`sk-...`, `AKIA...`, `-----BEGIN PRIVATE KEY-----`, `xox*-` Slack 토큰)에서 매치 0건(`git ls-files | xargs grep -E ...` 종료코드 1=무매치).
- `.env`는 추적되지 않음 — `.gitignore`에 `.env` / `.env.*` (단 `!.env.example` 예외)로 등재. `git ls-files`에 잡히는 env 파일은 `.env.example`과 `frontend/.env.example`(둘 다 예시/플레이스홀더)뿐. `frontend/.env.example`의 `LLM_API_KEY=<team-provided-key>`는 플레이스홀더이며 실제 키 아님(`frontend/.env.example:8`).
- 클라우드 OpenAI 키, Neo4j 자격증명은 모두 `.env.example`에서 빈 값(`.env.example:1,22-25`).
- **내부 인프라 엔드포인트 노출 경고**: 자격증명은 아니나 내부망 정보가 tracked 파일에 평문 노출됨. Tailscale 호스트 `mac-mini-m4-llm.tail023e97.ts.net`와 폴백 IP `100.103.82.56`가 `.env.example:8-9,19`, `frontend/.env.example:7`, `RUN.md:60-61`에 기재. 공개 repo 전환 시 tailnet 도메인/IP는 정찰 표면이 되므로 마스킹 권장.
- **이미 확인된 사실 명시**: git 히스토리 61커밋 비밀정보 스캔에서 실제 자격증명 없음(clean). 본 정적 점검(현재 tree)도 동일하게 실제 키/비번 없음으로 일치.

---

## 캄보디아 확장 지점 (KH Jurisdiction Expansion)

전제: 분석 결과 §8(F10)·§5(F4)가 확정했듯, 현 코드베이스에는 jurisdiction/ruleset/country/locale 추상화가 **전무**하며(백엔드 strict grep 0건, 프론트 `src` 0건), 유일한 격리 키는 `workspace_id`다(기본값 `graphcompliance_mvp_jb_20260530`, schemas.py:40). 따라서 KH 확장의 1차 데이터 격리는 `workspace_id` seam(예: 별도 KH 전용 workspace_id 적재)으로 즉시 달성 가능하나, 이는 "데이터 격리 seam"일 뿐 "jurisdiction-aware 로직 seam"은 아니다. 아래는 jurisdiction을 명시적 차원으로 추가하는 정확한 지점이다.

### (A) jurisdiction="KH" 분리 서브그래프(KR과 엣지 없음) 추가

- seam: policy_compiler.py:`_write_compiled()`(:521) — PolicyHypernym 생성 `MERGE (h:PolicyHypernym {id, workspace_id})`(:527-528)의 `SET h += row`에서 `row`에 `jurisdiction`을 채우거나 `SET h.jurisdiction = $jurisdiction` 추가. id 키에는 넣지 말 것(아래 (B) id 재설계와 결합되어야 KR/KH 동일개념 충돌 방지).
- seam: policy_compiler.py:`_write_compiled()`(:534-538) — Premise 생성 `MERGE (p:Premise {id, workspace_id})`의 `SET p += $props`에서 `props`(premise dict)에 `jurisdiction` 필드 추가.
- seam: policy_compiler.py:`_write_compiled()`(:589-602) — `CULegalElementProfile` 생성 `MERGE (profile:CULegalElementProfile {id, workspace_id})`의 `$props`에 `jurisdiction` 추가. CU 본체(ComplianceUnit) 노드는 이 파일에서 **MATCH만 됨**(:573, :592, retriever.py:178; F4·F10 확인) — CU 자체 태깅은 외부 CU 적재기를 고쳐야 함(불확실: 그 적재기는 repo 평면 .py에 부재).
- seam: legal_elements.py:`build_legal_element_profile_from_compiler_row()`(:234-256 반환 dict) — CU 법적 프로파일 빌드 단계. `applicability_scope`(:240, :252) 옆에 `jurisdiction`을 별도 차원으로 추가(scope 토큰에 끼워넣지 말 것 — scope는 product_group/channel 의미로만 정규화됨, retriever.py:517-541). 이 값이 위 `_write_compiled()`의 `$props`로 흘러 들어감.
- 스키마(라벨/인덱스): 정적 코드에 `CREATE CONSTRAINT` 없음(F3, grep 0건). jurisdiction 프로퍼티는 `PolicyHypernym`·`Premise`·`CULegalElementProfile`(+외부 적재 `ComplianceUnit`)에 추가. 인덱스는 `_ensure_vector_indexes()`(policy_compiler.py:604-622)가 벡터 인덱스만 생성하므로, jurisdiction RANGE 인덱스가 필요하면 동일 함수에 `CREATE INDEX ... FOR (n:ComplianceUnit) ON (n.jurisdiction) IF NOT EXISTS` 형태로 추가.
- KR↔KH 엣지 차단 보장: 모든 관계 MERGE가 `{workspace_id: $workspace_id}` 한 값으로 스코프되고(예: `DERIVES_PREMISE`/`DEFINES_HYPERNYM`/`SUPPORTS_CU` policy_compiler.py:543·549·558, `HAS_SUBJECT_HYPERNYM` :580, `HAS_LEGAL_ELEMENT_PROFILE` :595), 모든 노드 MATCH도 `{id, workspace_id}` 또는 `{workspace_id}`로 묶이므로(:541, :547, :556, :573, :579, :592) — **KH를 별도 workspace_id로 적재하면 컴파일러가 KR 노드를 MATCH조차 못 해 교차 엣지가 구조적으로 생성 불가**다. 동일 workspace_id 내에서 jurisdiction 프로퍼티로만 분리하려면, 위 모든 MATCH의 매치 패턴에 `{jurisdiction: $jurisdiction}`을 추가해야 KR PolicyHypernym↔KH Premise 같은 교차 엣지를 막을 수 있다. 권장: **workspace_id 분리(가장 비용 낮고 엣지 차단 자동)** + jurisdiction 프로퍼티(질의 라우팅용) 병행.

### (B) Claim 추출 LLM을 언어중립 PolicyHypernym 개념 ID로 매핑

- 현황(확정): PolicyHypernym은 **언어중립 ID가 아니라 한국어 문자열 기반**이다. `id = stable_id("policy_hypernym", workspace_id, domain, name)`(policy_compiler.py:440)이고 `stable_id`는 입력을 `"||".join` 후 SHA-256 해시(utils.py:11-13) — 즉 id는 한국어 `name`의 함수다. 게다가 `is_korean_canonical_label()`(policy_compiler.py:740-746)이 한글 음절(U+AC00–U+D7A3) 미포함 시 False를 반환하고, `validate_compiler_output()`(:666-668)이 이를 강제, 컴파일러 system 프롬프트도 "name must be a Korean canonical label"을 명시(:406-409). 따라서 같은 개념(예 "원금보장")이라도 KR·KH 코퍼스에서 서로 다른 id의 별개 노드로 갈라진다(F4 §5 확정).
- seam: policy_compiler.py:`is_korean_canonical_label()`(:740-746) + `validate_compiler_output()`(:666-668) — 한글 강제 검증을 다국어 허용으로 완화. 단, 이것만으로는 id가 여전히 표시 라벨의 해시라 언어별 분기 문제 미해결.
- seam: policy_compiler.py:`_normalize_compiled()`(:440) — **언어중립 concept_code를 도입하고 `stable_id`의 해시 입력을 `name`이 아니라 그 concept_code로 교체**해야 KR "원금보장"과 KH "ការធានាដើមទុន"이 동일 id로 수렴. `name`은 언어별 표시 라벨로만 남김. (불확실: concept_code 부여 주체 — 컴파일러 LLM 출력(`COMPILER_SCHEMA.policy_hypernyms`, policy_compiler.py:53-66)에 필드를 추가할지, 외부 온톨로지 매핑으로 줄지는 설계 결정.)
- seab: vocabulary_governance.py:`_write_governed()`(:166-177) — 거버넌스 2차 패스가 `name`을 `canonical_name_ko`로 덮어쓰고(:167-169) `aliases`를 강제(:198-199). KH 도입 시 `canonical_name_ko`/`description_ko`/한국어 별칭 강제를 언어 일반화(예 `canonical_name_{lang}`)로 변경. 단 이는 표시 라벨 정규화일 뿐 언어중립 앵커가 아니므로 (B)의 concept_code 도입이 선행 전제.
- seam(크메르어/영어 광고 → 개념 ID 매핑 경로): normalizer.py:`PolicyGuidedNormalizer.normalize()`(:66). 허용 vocabulary는 코드 하드코딩이 아니라 `policy_context["hypernyms"]`에서 동적 주입되고(:74-78), `normalization_schema_for_allowed_ids()`(:184-191)가 LLM의 `hypernym_id`를 승인된 id enum으로 스키마 강제. **따라서 KH PolicyHypernym이 KH workspace에 적재되어 있으면 retriever가 그 id들을 주입하므로, normalizer는 별도 코드 변경 없이도 KH id를 매핑할 수 있다.** 다만 정규화 system 프롬프트(normalizer.py:113-124)가 한국어 scope qualifier 리터럴('누구나','조건 없이','확정','보장' 등 :120-123)을 하드코딩하고 "Korean financial-ad"로 못박혀 있어(:114), 크메르어/영어 광고에 대해 이 한국어 예시는 무력. → normalizer.py:114-123 system 프롬프트를 jurisdiction별로 분기(언어별 qualifier 예시 주입)해야 정상 동작.
- seam(상류 Claim 추출 프롬프트): context_extractor.py:`_extract_hierarchical_legacy()`(:319) system 프롬프트(:322-357) 및 staged 경로 system 프롬프트(:381-388·412-425·455-462). 전부 "Korean financial-advertising context graph extractor"(:323)로 시작하고 한국어 위험표현 리터럴('누구나'→target_scope, '보장'→guarantee 등 :335-341)을 하드코딩. → 크메르어/영어 광고를 위해 이 system 프롬프트 묶음을 jurisdiction/언어별로 분기(언어별 예시·언어 선언 치환). 추출 자체는 정규식이 아닌 LLM structured output이므로(F2 확인, context_extractor.py에 `re.` 부재) 정규식 포팅 부담은 없고 프롬프트 리터럴 교체가 핵심.

### (C) 입력에 관할 선택(KH/KR)을 받아 KH 광고는 KH-태그 CU만 게이팅/검색/판정하도록 라우팅

- seam: schemas.py:`ReviewInput`(:37-47) — `jurisdiction: str = "KR"`(또는 `"KH"`) 필드 추가. 현재 frozen dataclass에 `workspace_id`/`product_group`/`channel`만 존재.
- seam: workflow.py:`review_input_from_payload()`(:510-524) — `jurisdiction=str(payload.get("jurisdiction", "KR"))` 한 줄 추가(현재 :518~523 패턴 그대로). 이것이 payload→ReviewInput 계약 확장의 단일 지점.
- seam: server.py:`/api/review`(:61) `record_run(...)`(:67-79) 및 `/api/review/stream`(:116) `record_run(...)`(:133-145) — 두 곳 모두 `jurisdiction=str(payload.get("jurisdiction") or "")`를 추가해 run 스냅샷에 보존(현재 `workspace_id` 등과 동일 패턴). `workflow_for()`(:37-46)는 모델만 보므로 변경 불필요.
- seam(workflow 오케스트레이션 분기): workflow.py:`review_events()` 내 `self.retriever.assert_policy_alignment_ready(workspace_id=...)`(:83), `policy_context_for_claims(...)`(:125-129), 그리고 CU 후보검색 호출 `candidates_for_anchor(...)`(:276-282) — 현재 `workspace_id`·`product_group`·`channel`만 전파. 여기에 `jurisdiction=review_input.jurisdiction`을 함께 전파(동일 전파 경로를 그대로 따라가면 됨, F10 §8.4 확인).
- seam(retriever 시그니처+쿼리): retriever.py:`candidates_for_anchor()`(:149-157) — 시그니처에 `jurisdiction: str` 추가하고, 메인 Cypher의 CU 매치 `MATCH (cu:ComplianceUnit {workspace_id})-[:HAS_EMBEDDING_PROFILE]->(profile) WHERE coalesce(cu.active_for_gate,false)=true`(:178-179)에 `AND cu.jurisdiction = $jurisdiction` 추가. seed PolicyHypernym 매치(:174-175)와 legal_profile 조인(:207)에도 jurisdiction을 둔 위치에 따라 `{jurisdiction: $jurisdiction}` 추가. `$jurisdiction` 파라미터를 `session.run(... )` 인자(:264-268)에 바인딩.
- seam(게이트 함수): retriever.py:`with_scope_gate()`(:458) — jurisdiction 불일치 CU를 `gate_status="suppressed"`로 후처리하는 보조 seam(쿼리 수정 없이 파이썬 레벨 차단 가능). applicability_gate.py:`gate_disclosure_catalog()`(:64-104)는 disclosure 카탈로그가 KH용으로 별도 적재될 경우 동일하게 jurisdiction 분기 필요. 단, **workspace_id 분리 적재 방식을 쓰면** CU 후보검색 쿼리가 이미 `{workspace_id}`로 묶여 있어(:178) KH workspace로 호출하는 것만으로 KH CU만 검색됨 — 쿼리 jurisdiction 절은 "동일 workspace 내 혼재" 시에만 필수.
- 판정 라우팅: 위 CU 검색이 KH-태그 CU만 반환하면 다운스트림 판정(`judge.judge()` workflow.py:422)·예외 override(:442-464)는 자동으로 KH CU에만 적용된다(별도 jurisdiction 분기 불필요 — cu_plan이 이미 필터된 결과). 단 judge/normalizer/extractor의 한국어 system 프롬프트(B 참조)는 언어별 분기 필요.

### (D) 프론트엔드 관할 토글 + 결과 표시

- 현황(확정): frontend/src 전역에 jurisdiction/region/locale 개념 없음(F9, grep 0건; `ko-KR`은 날짜 포맷 로케일뿐). 핵심 seam은 **(2) 타입 + (3) buildPayload 한 줄**이며 이 둘만으로 백엔드까지 관할 신호 전달.
- seam: lib/labels.ts — `CHANNELS`(:258-265)·`PRODUCT_GROUPS`(:250-256) 옆에 `JURISDICTIONS = [{value:"KR",label:"한국"},{value:"KH",label:"캄보디아"}] as const` 신설. (KH 채널/상품군/고지 카탈로그가 KR과 다르면 여기서 관할별 분기.)
- seam: lib/types.ts:`ReviewRequest`(:619-632) — `jurisdiction?: string` 추가(백엔드 계약 확장). `RunSummary`(:286-310)에도 `jurisdiction?` 추가 시 대시보드/재실행에서 보존.
- seam: components/ReviewForm.tsx — 상태 `const [jurisdiction, setJurisdiction] = useState(draftPreset?.jurisdiction ?? "KR")`를 기존 useState 블록(:36-46)에 추가; 상품군/채널 `<select>` 그리드(:190-219)에 동일 패턴 관할 `<select>`(JURISDICTIONS 매핑) 추가; `buildPayload()`(:93-103) 객체에 `jurisdiction` 한 줄 추가(큐 항목은 `...buildPayload()`/`...item` 전개라 자동 포함, :111-114·:127-134).
- seam: app/page.tsx:`handleEditRun()`(:112-127) — `RunSummary`→`draftPreset` 이동 시 `jurisdiction: run.jurisdiction` 추가해야 재실행 시 관할 보존(`handleUsePreset` :103-110은 `...preset` 전개라 자동).
- seam: components/shell/ContextBar.tsx — 관할 배지를 보이려면 (a) page.tsx `handleSubmit`(:44-58)·`handleOpenRun`(:87-101)의 `setMeta`에 `jurisdictionLabel` 추가, (b) ContextBar props 전달(page.tsx:167-174), (c) ContextBar.tsx 제목/`review_run_id` 영역(:24-37)에 배지 렌더. `ReviewMeta`(page.tsx:28-31)는 현재 `title`/`channelLabel`만 보유.
- seam(선택): components/shell/Sidebar.tsx ReviewRun 카드(:84-106) 또는 tabs/DashboardTab.tsx 집계(:170-175)에 `run.jurisdiction` 기반 필터/분포 추가. 불확실: 백엔드 `/api/runs` 응답에 jurisdiction이 실리는지는 run_store 스냅샷 요약 필드 확장((C)의 `record_run`)에 달림.

[검증한 절대경로]
- /Users/kunwoo/Desktop/workspace/junbub/repo/policy_compiler.py (521-602: PolicyHypernym/Premise/CULegalElementProfile 쓰기, MERGE 패턴 직접 확인)
- /Users/kunwoo/Desktop/workspace/junbub/repo/retriever.py (74-144: assert_policy_alignment_ready/policy_context_for_claims workspace 스코프; 149-278: candidates_for_anchor 시그니처·메인 Cypher 직접 확인)
- /Users/kunwoo/Desktop/workspace/junbub/repo/normalizer.py (66-191: normalize 동적 vocabulary 주입·schema enum 강제·한국어 프롬프트 리터럴 직접 확인)
- /Users/kunwoo/Desktop/workspace/junbub/repo/context_extractor.py (310-364: legacy 추출 system 프롬프트 한국어 하드코딩 직접 확인)
- /Users/kunwoo/Desktop/workspace/junbub/repo/server.py (37-145: workflow_for·/api/review·/api/review/stream·record_run 인자 직접 확인)
- /Users/kunwoo/Desktop/workspace/junbub/repo/workflow.py (270-289: candidates_for_anchor 호출부; 510-524: review_input_from_payload 직접 확인)
- /Users/kunwoo/Desktop/workspace/junbub/repo/schemas.py (25-47: ReviewInput/CULegalElementProfile dataclass 직접 확인)

---
