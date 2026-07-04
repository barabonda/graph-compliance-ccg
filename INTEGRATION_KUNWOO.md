# `kunwoo` 브랜치 통합 가이드 — 캄보디아(PPCBank) 다국어 확장

> **이 문서는 main으로 통합하는 Claude Code(통합 담당자)를 위한 것입니다.**
> 작성: kunwoo · 2026-07-04 · 상세 이력: [docs/CHANGELOG_FEATURES.md](docs/CHANGELOG_FEATURES.md) · 표 요약: [docs/CHANGELOG_KH_요약.md](docs/CHANGELOG_KH_요약.md)

---

## 1. 이 브랜치가 추가하는 것 (한 줄 요약)

기존 KR 심사 파이프라인을 **한 줄도 회귀시키지 않으면서**, 캄보디아(PPCBank) 관할을 통째로 추가:
**법률 기반 policy graph**(CU 16) + **상품설명서 기반 product fact graph**(상품 20종·사실 255건, Claude Opus 4.8 추출) + **다국어 심사 UI**(문장별 EN/KO 번역) + **결과 설명 챗**.

- 베이스 커밋: `121ab3a` (main과 공통 조상)
- 이 브랜치 커밋: `597f2ed`(backend) → `cc7a6f9`(frontend) → `5264a6f`(data) → docs 커밋
- 격리 키: **`workspace_id = graphcompliance_cambodia_ppcbank_20260630`** — 모든 KH 노드/엣지/분기가 이 값 하나로 게이트됨. KR workspace는 건드리지 않음.

## 2. KR 무회귀 원칙 (통합 시 반드시 유지)

모든 KH 동작은 **env 게이트 뒤에** 있습니다. env를 설정하지 않으면 코드 경로가 KR 기존과 동일합니다.

| env (이름만; 값은 kunwoo에게 요청) | 역할 | 미설정 시 |
|---|---|---|
| `CCG_NON_KR_LAW_WORKSPACES` | 비-KR 판정에서 한국법 하드코딩 제거 + 표시용 번역 생성 | KR 프롬프트 **바이트 동일** |
| `CCG_PRELOADED_PRODUCT_FACTS_WORKSPACES` | Neo4j 선적재 ProductFact 우선 사용(재추출 생략) | KR은 기존 PDF 온디맨드 추출 그대로 |
| `CCG_MIN_HYPERNYM` / `CCG_MIN_PREMISE` (+ `CCG_MIN_*_<ws>`) | 정렬층 준비 게이트 임계값 workspace별 조정 | KR 기본 30/100 불변 |
| `TEAM_NEO4J_URI` / `TEAM_NEO4J_USER` / `TEAM_NEO4J_PASSWORD` / `TEAM_NEO4J_WORKSPACES` | KR 코퍼스 **읽기**를 팀 Aura(`69f0e4a9`)로 라우팅 | 전부 기본 `NEO4J_*` DB 사용 |
| `NEO4J_URI/USER(NAME)/PASSWORD/DATABASE` | KH 그래프 + 심사 산출물 저장소(kunwoo 샌드박스 `7349cbb2`) | — |
| `ANTHROPIC_API_KEY` | **오프라인 상품사실 추출 전용**(`build_ppcbank_product_graph.py`) | 라이브 심사는 OpenAI만 사용, 불필요 |
| `WORKSPACE_ID`, `JB_PRODUCT_DISCLOSURE_ROOT`, `OPENAI_API_KEY` | 기존과 동일 의미 | — |

**2-DB 아키텍처(팀 합의 반영)**: 팀 Aura에는 **새 노드/엣지를 만들지 않는다**는 합의에 따라, KR 코퍼스 *읽기*만 팀 DB로 라우팅(`retriever._session_for`, `legal_hierarchy`, copilot 조회)하고, **심사 산출물 쓰기(persistence/run_store)는 항상 샌드박스**에 저장합니다. 검증: KR 라이브 심사 전후 팀 DB 노드/엣지 수 완전 동일(77,702/151,908).

## 3. 신규 파일 (충돌 없음 — 그대로 추가)

**백엔드**
| 파일 | 역할 |
|---|---|
| `ad_translation.py` | 비-KR run 표시용 EN/KO 번역(`ad_translations{en,ko,sentences[],note}`). 판정 완료 후 1회 호출, 내용 해시 캐시, 실패 시 null. **판정 파이프라인 불개입** |
| `copilot_tools.py` | 읽기 전용 도구 5종: `list_runs`·`get_run_detail`·`compare_runs`·`get_product_facts`·`get_cu_detail`(+ workspace별 팀 DB 라우팅) |
| `ingest_cambodia.py` | KH 법령 적재: CU 16(광고규제 14·설명의무 2)·LegalClause 14·LegalChunk 7·근거엣지 29. 전 노드 `effective_date/version/source_date` |
| `ingest_cambodia_products.py` | (CC-6 초기) 수기 상품사실 로더 — 현재는 아래 스크립트가 대체, 참고용 |
| `build_ppcbank_product_graph.py` | **product fact graph 빌더**: `--crawl`(상품페이지 수집) → `--extract`(Claude Opus 4.8·영어 프롬프트·근거 verbatim 인용·미공시도 `*_disclosure` 사실로) → `--ingest`(KH MERGE, idempotent) → `--verify` |

**프론트엔드**
| 파일 | 역할 |
|---|---|
| `frontend/src/components/CopilotPanel.tsx` | `/api/copilot` 경량 챗 사이드패널(읽기 전용 명시, 도구 호출 칩 표시) |

**데이터** — `data/cambodia/` (5.3MB): 법령 원문(PDF+조문 JSON+요약), PPCBank 상품페이지 20종 크롤(html+정제 텍스트), Claude 추출 결과(`products/_claude_facts.json`), 평가셋(`eval/kh_eval_v0.json`+러너+리포트)

**문서** — `docs/CHANGELOG_FEATURES.md`(CC-2~CC-12 상세), `docs/CHANGELOG_KH_요약.md`(제출 양식 표), `docs/DEMO_KH.md`(시연 스크립트), `docs/KH_지식그래프_공유.pptx`(팀 공유 3장), `docs/CODE_ANALYSIS.md`(KH 착수 전 작성한 아키텍처 분석 — 읽기 전용 참고), `RUN.md`(로컬 실행 가이드; 이전 커밋 포함분)

## 4. 수정 파일 — 변경 내용과 병합 지침

### 4a. ⚠ main(7b2ea18)과 **양쪽 모두 수정** — 충돌 예상 13건

main의 `feat: guideline-tier grounding, redesigned review console, compliance copilot`과 겹칩니다. 파일별 지침:

| 파일 | kunwoo 쪽 변경(의미 단위) | 병합 지침 |
|---|---|---|
| `utils.py` *(main 미수정)* | **`uses_korean_law_context(workspace_id)` 신규 정의**(+16줄, `CCG_NON_KR_LAW_WORKSPACES` 게이트) — judge/router/policy_evidence/workflow/ad_translation **5개 모듈이 임포트** | **가장 먼저 이식**(순수 추가 함수). 누락 시 아래 분기들 전부 ImportError |
| `judge.py` | `uses_korean_law_context()`(utils.py) 분기: 비-KR이면 프롬프트의 금소법 위임 예시 제거(+19줄) | **분기만 이식**. KR 경로 문자열은 그대로여야 함 |
| `policy_evidence.py` *(main 미수정)* | 비-KR이면 한국법 DELEGATES_TO 엣지 생략 | 충돌 없음 |
| `legal_hierarchy.py` *(main 미수정)* | `_creds_for_workspace()` — KR 코퍼스(모법 병기) 읽기를 팀 Aura(`TEAM_NEO4J_*`)로 라우팅(+20줄, retriever/copilot_tools와 동일 규칙) | 충돌 없음, 그대로 |
| `router.py` | 비-KR이면 금소법 §22 하드코딩 프롬프트 분기 제거(6줄) | 분기만 이식 |
| `retriever.py` | ① `alignment_min_thresholds()` env화 ② `_session_for(workspace_id)` 팀DB 읽기 라우팅(+89줄) | 두 기능 모두 additive 함수 — main의 guideline-tier 변경과 의미 충돌 없음, 텍스트 충돌만 해소 |
| `product_facts.py` | ① `load_preloaded_product_facts()`+`preloaded_facts_enabled()` 선적재 우선 분기 ② 경로곱 중복 `DISTINCT` 수정(+138줄) | analyze() 진입부의 분기 블록 통째로 이식 |
| `workflow.py` | `review_input_from_payload`에 `language`·`selected_product_*` 배선, workspace_id 스레딩(+23줄) | 필드 배선만 이식 |
| `schemas.py` *(main 미수정)* | `ReviewInput.language`(기본 "ko", 메타데이터 전용) | 한 필드 추가 |
| `run_store.py` | run 요약/스냅샷에 `workspace_id`·`language` 보존(+4줄) | 그대로 |
| `server.py` | ① `record_run` 2곳에 ws/lang 전달 ② `POST /api/copilot` ③ `/api/product-doc`: KR CSV 미스 시 **Neo4j ProductDocument 폴백**(source_url 307 리다이렉트) — KR PDF 경로·traversal 가드 불변(+150줄) | 엔드포인트 단위로 이식. main과 라우트명 충돌 시 §4b 참고 |
| `frontend/src/app/page.tsx` | CopilotPanel 마운트(+7줄) | §4b 결정에 따름 |
| `frontend/.../AdPane.tsx` | **문장별 EN·KO 인라인 병기**(sentence_id 매핑) + 접이식 전문 번역 + 교차언어 개념 패널(+136줄). 하이라이트는 원문 전용 | main이 콘솔을 리디자인했으므로 **텍스트 병합보다 기능 재이식 권장**: `sentenceTranslationsById(result)`로 문장별 번역을 원문 각 줄 아래 렌더 |
| `frontend/.../RiskList.tsx` | 위험 카드 인용문 아래 번역(`translationForQuote`)(+21줄) | 동일 — 기능 재이식 |
| `frontend/src/lib/selectors.ts` | `sentenceTranslationsById()`·`translationForQuote()` 추가(+36줄, 순수 함수) | 함수 2개 추가 — 충돌 시 그대로 append |
| `frontend/src/lib/types.ts` | `ad_translations` 타입(+13줄) | 그대로 |
| `frontend/src/lib/labels.ts` | `JURISDICTIONS`·`KH_WORKSPACE_ID`(+9줄) | 그대로 |
| `frontend/.../ReviewForm.tsx` *(main 미수정)* | 관할(시장) 선택 → `workspace_id`+`language` payload | 충돌 없음 |

### 4b. ⚠ 코파일럿 중복 — 설계 결정 필요

- **main**: CopilotKit 기반 compliance copilot(+ `.agents/skills/copilotkit-*` 다수)
- **kunwoo**: CopilotKit을 검토했으나 v1.62가 자체 Node CopilotRuntime(GraphQL 내 LLM 루프)을 요구해 파이썬 단일 tool-loop 설계와 충돌 → **자체 경량 패널 + `POST /api/copilot`**(chat.completions function-calling, 최대 6회, 판정 변경 불가)로 구현

**권장**: UI는 main의 CopilotKit 콘솔을 유지하되, **`copilot_tools.py`(도구 5종 + 팀DB 라우팅)는 백엔드 자산으로 보존** — 어떤 UI에서도 재사용 가능하고, KH run 설명(`get_product_facts`·`get_cu_detail`의 KH/KR 라우팅)은 이 모듈에만 있음. `CopilotPanel.tsx`·`/api/copilot`은 main UI가 대체하면 제거해도 무방.

### 4c. 의도적으로 커밋하지 않은 것

- `frontend/package-lock.json` — package.json 변경 없는 순수 churn(-114줄)이라 제외. **CopilotKit은 의존성에 추가되지 않았음**
- `.env`(gitignore) — 모든 키/비번은 값이 아니라 이름만 이 문서에 기재. 값은 kunwoo에게 별도 채널로 요청

## 5. 구축된 그래프 현황 (kunwoo 샌드박스 `7349cbb2`, 실측)

| 항목 | 값 |
|---|---|
| ComplianceUnit | 16 (광고규제 14·설명의무 2) — **16/16 법조문 근거 연결**, 룰당 근거 조문 평균 1.8 |
| 정렬층 | PolicyHypernym 13 · Premise 19 · CU임베딩/법요소 프로파일 16+16 · 벡터 인덱스 ONLINE |
| Product / 문서 / 사실 | 20종(예금10·대출7·카드3) / 21건 / **ProductFact 255건**(미공시 53, 신뢰도 평균 0.91, `extraction_method=claude:claude-opus-4-8`) |
| 규모 | 코퍼스 413 노드 · workspace 전체 3,287 노드/5,125 관계(심사 16회 산출물 포함) |
| 품질 | 근거문구 원문 일치 96.5%(결정적) · 독립 LLM 감사(24 에이전트, 전수 대조+적대 재검증) **99.2% 충실, EXCELLENT 92/100** · 발견 오류 2건 수정 후 재적재 · 격리 위반 0 |

재구축: `python3 build_ppcbank_product_graph.py --all --replace-facts` (ANTHROPIC_API_KEY 필요; 1회 ~$1)

## 6. 검증 상태

- `test_workflow.py` 46 pass(기존 pre-existing 실패 7건 외 신규 실패 0)
- KR 라이브 심사 E2E: reject + 실제 KR 조문 인용, `ad_translations=null`, 팀 DB 노드/엣지 무변경
- KH E2E: 크메르어 광고 → KH-CU만 발화, 캄보디아 조문만 인용, 문장별 번역 렌더; Home Loan 위반 광고 → PRELOADED·CONTRADICTED 5(반려)
- 평가셋: `data/cambodia/eval/` 5건 + 플래그십 3회 반복 안정성(리포트 동봉)

## 7. 알려진 한계 (통합 후 과제)

1. 상품 검색 workspace가 env(`WORKSPACE_ID`) 고정 + `lru_cache` — KR·KH 혼합 단일 배포는 per-review 스레딩 필요. **상품 적재 후 백엔드 재기동 필수**(캐시 갱신)
2. NBC 금리상한: 원문 미확보(citation-only placeholder)
3. KH 코퍼스는 캄보디아 법률 전문가 검증 전(PoC; 노드에 `poc=true, lawyer_verified=false` 마킹)
4. 고지 카탈로그(`disclosure_catalog.py`)는 한국어 기반 유지(KH 고지 별도 과제)
5. 리뷰 영속화가 상품명 기준 중복 Product 노드를 만들 수 있음(동일 문서 공유 + 런타임 `DISTINCT`로 무해; 정리 루틴은 선택 과제)

## 8. 권장 통합 순서 (체크리스트)

1. [ ] 신규 파일 전부 추가(§3 — 충돌 없음)
2. [ ] 백엔드 겹침 파일: kunwoo 쪽 **의미 단위**(env 분기·함수)를 main 코드에 이식(§4a 표)
3. [ ] 프론트: `types.ts`·`labels.ts`·`selectors.ts` 먼저(순수 추가) → main의 새 콘솔에 번역 렌더 기능 재이식(AdPane·RiskList)
4. [ ] 코파일럿 결정(§4b): main UI 유지 + `copilot_tools.py` 보존 권장
5. [ ] env 이름 채우기(§2; 값은 kunwoo에게) 후: KR 회귀(`test_workflow.py` + KR 심사 1건, 번역 null 확인) → KH 스모크(`run_kh_eval.py` 1건)
6. [ ] `WORKSPACE_ID` 정책 결정(단일 배포면 KH/KR 중 택1 또는 per-review 스레딩 과제로)

## 9. 추가 업데이트 (2026-07-04, CC-13)

원격 팀원이 Aura에 직접 접속해 text2cypher/쿼리로 상품 문서를 조회할 때 로컬 파일 없이도 내용이 나오도록 보강. 전부 **additive**(기존 스키마·라이브 심사·KR 무영향), KH workspace 한정.

- **`build_ppcbank_product_graph.py`** (M): 각 `ProductDocument`에 크롤 전문을 `full_text`(+`content_chars`) 속성으로 임베드(신규 `clean_doc_text()`). 문서 노드가 포인터만이 아니라 본문을 자체 보유.
- **`structure_ppcbank_docs.py`** (신규): 문서를 **구조화 그래프**로 분해(하이브리드 GraphRAG) — `(:ProductDocument)-[:HAS_SECTION]->(:DocSection)` 아래 표를 셀 단위 노드로: `RateEntry{term_months,currency,channel,payment,rate_kind,holding_period,amount_tier,rate_pa}`·`EligibilityItem`·`LoanCondition`·`FeeItem`, 산문은 `DocChunk`(`NEXT` 체인). Claude Opus 4.8 오프라인 추출(`--structure/--ingest/--verify/--all/--replace`). 규모: DocSection 112·RateEntry 202·EligibilityItem 99·LoanCondition 64·FeeItem 51·DocChunk 262. 검증: 금리 매트릭스 원문 셀 12/12, 24-에이전트 적대적 감사 GOOD 85→수정 후 금리셀 178/178 정확. 새 라벨(`DocSection`/`RateEntry`/`EligibilityItem`/`LoanCondition`/`FeeItem`/`DocChunk`)은 KR 스키마와 무충돌.
- **`server.py`** `/api/product-doc/{id}` (이미 이전 커밋 포함): KR 공시 CSV에 없으면 Neo4j `ProductDocument`로 폴백해 `source_url` 307 리다이렉트(웹 소스 상품용). KR PDF 경로 불변.
- **데이터**: `data/cambodia/products/_doc_structure.json`(구조화 결과), 실제 **크메르어** 페이지 크롤(`ppcbank_*_km.{html,txt}`), 복사용 광고 원문 `docs/ppcbank_ad_samples/`(영어·크메르어).
- 재현: `python3 build_ppcbank_product_graph.py --all --replace-facts && python3 structure_ppcbank_docs.py --all`(둘 다 `ANTHROPIC_API_KEY` 필요).
