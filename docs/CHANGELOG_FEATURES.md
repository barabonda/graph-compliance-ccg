# Feature Changelog

Newest first. 캄보디아(KH) 관할 확장 항목은 본선 제출 양식(변경 일자 / 대상 기능 / 변경 내용 / 변경 사유)으로 정리.
한국어 표 요약본: [CHANGELOG_KH_요약.md](CHANGELOG_KH_요약.md) · 공통 격리 키: `workspace_id=graphcompliance_cambodia_ppcbank_20260630` (KR 데이터·경로 불변)

---

## 변경 일자: 2026-07-04 · 대상 기능: 라이브 심사 Claude 모델 Provider 지원
- **변경 내용**: `llm_gateway.py`에 Anthropic Messages API provider를 추가해 `claude-*` 모델 선택 시 OpenAI가 아니라 Anthropic으로 구조화 출력을 호출하도록 확장. 지원 모델 후보는 공식 Claude 모델 표기 기준 `claude-sonnet-5`, `claude-fable-5`, `claude-opus-4-8`, `claude-opus-4-6`, `claude-haiku-4-5-20251001`이며, 프론트 모델 선택 목록에도 추가. Anthropic 호출은 tool-use 강제(`tool_choice`)와 JSON schema를 사용해 기존 CCG의 structured extraction/judge 계약을 유지한다. `.env.example`에는 `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `CCG_ANTHROPIC_*` 타임아웃/출력 설정을 추가했다.
- **변경 사유**: 긴 금융광고 문안과 상품문서 대조 단계에서 OpenAI 모델만 고정하지 않고 Claude 계열 모델을 실험·운영할 수 있게 하기 위함. 모델 선택은 요청 payload 또는 단계별 `CCG_*_MODEL` 환경변수에서 `claude-*`를 지정하는 방식이며, 최종 판정 로직/그래프 게이트/Neo4j 저장 계약은 유지한다.
- **검증**: `py_compile` 통과, 프론트 모델 라벨 syntax check 통과, Anthropic provider 라우팅 unit test 통과. 전체 `test_workflow.py`에는 기존 FakeLLM revision fixture와 관련된 실패가 남아 있어 별도 정리 필요.

## 변경 일자: 2026-07-03 · 대상 기능: Claude Opus 4.8 상품 사실 그래프 확장 (CC-12)
- **변경 내용**: 신규 `build_ppcbank_product_graph.py`(4단계: `--crawl` 상품페이지 수집 → `--extract` Claude Opus 4.8 영어 추출 → `--ingest` KH workspace MERGE → `--verify`). PPCBank 개인뱅킹 상품 **20종(예금 10·대출 7·카드 3)** 페이지를 크롤(HTML→표 셀 `|` 보존 텍스트, 기존 정기예금·자동차대출 `.md` 재사용)하고, **영어 추출 프롬프트**(컴플라이언스 지향: 근거 문구 verbatim 필수·추정 금지, 심사 핵심 "미공시(absence)"도 `*_disclosure` 사실로 기록, 조건 qualifier는 `condition`에)로 문서 21건에서 **ProductFact 255건**을 추출 → KH workspace에 MERGE. 사실 노드에 `extraction_method="claude:claude-opus-4-8"`·`ingest_source=ppcbank_poc`·`poc/lawyer_verified` 마커, `Product.source`·`HAS_PRODUCT_DOCUMENT` edge source는 라우팅 하드필터(jb_data_context.py:483-484) 요구로 로더 상수 유지. `--replace-facts`로 CC-6 수기 7건을 정리해 provenance 통일(중복 방지). 구조화 출력은 강제 `tool_choice`+스키마, 시스템 프롬프트 prompt caching(첫 호출 후 `cache_read=1,718`). **라이브 심사 파이프라인은 OpenAI 그대로(`llm_gateway.py` 무변경)** — Claude는 오프라인 적재 경로에서만 호출. 키는 `.env`의 `ANTHROPIC_API_KEY`(gitignore·커밋/유출 금지)로만 저장. 새 상품이 콘솔 검색에 보이도록 백엔드(uvicorn :8770) 재기동해 `load_product_rows_from_neo4j` lru_cache 갱신.
- **변경 사유**: 상품 사실 그래프를 수기 2종에서 20종으로 확장 — 대회 제공 Claude API 이용권($450, 실사용 ~$1)으로 성능 우수한 모델(Opus 4.8)을 사용해 구축(정확도 우선; 비용은 무시 가능 수준). 검증: 격리 `ppcbank_poc` 노드 KH 밖 **0건**(KR·팀 DB 무변경, 쓰기는 내 샌드박스 7349에만), 런타임 `load_preloaded_product_facts`가 신상품 정상 반환(Home Loan 11·Visa Credit 13·Car for Cash 11), 신상품 E2E 심사(Home Loan 위반 광고: "모두에게 최저금리 무조건·누구나 즉시승인·집값 100% 대출") `extraction_status=PRELOADED`·상품사실 11건·대조 **CONTRADICTED 5 / CONDITION_MISSING 2 / PROMINENCE_INSUFFICIENT 1**(‘모두에게 최저’↔기간·비율별 차등·‘From 6.99%’, ‘무조건/즉시승인’↔자격요건·승인기준 미공시, ‘100%’↔LTV 80% 사실). 참고: CC-6 대비 Fixed Deposit은 상품페이지+금리개정 2문서 27건으로 재추출; 과거 리뷰 영속화가 만든 중복 Product 노드(src=None)는 동일 문서를 공유해 런타임 `DISTINCT`로 무영향(신규 중복 생성 없음).
- **감사·수정(같은 날)**: 사실 255건 전수를 독립 LLM 감사(에이전트 24개, 원문 1:1 대조 + 적대적 재검증)로 점검 → **EXCELLENT 92/100·99.2% 충실**. 발견된 실오류 2건을 `_claude_facts.json` 수정 후 재적재: Home Loan `approval_conditions_disclosure`가 "승인기준 미공시"로 오판(페이지 "TO APPLY"에 기준 있음) → "승인 *기간* 미공시"로 정정 · Current Account 자격서류에 NGO 섹션의 "MOU" 혼입 → "Memorandum and Articles of Association"로 정정. 빈 레거시 ProductDocument 1건 삭제(문서 21 정합).
- **버그 수정(같은 날)**: 상품 사실 대조 화면의 "상품페이지 보기"가 KH 상품에서 `document_not_found` → `server.py`의 `/api/product-doc/{id}`가 KR 공시 CSV(PDF)에서만 문서를 찾던 것을, **못 찾으면 Neo4j `ProductDocument` 노드로 폴백**해 `source_url`(실제 PPCBank 페이지)로 307 리다이렉트(없으면 로컬 크롤 스냅샷 inline)하도록 확장. KR PDF 경로·경로 traversal 가드는 그대로(미지 id는 여전히 404).

## 변경 일자: 2026-07-02 · 대상 기능: 문장별 참고 번역 병기 (CC-11)
- **변경 내용**: `ad_translation.py` 스키마에 `sentences[{original,en,ko}]` 추가 — 파이프라인의 문장 분할(`sentence_units`) 그대로 문장별 정렬 번역을 같은 1회 LLM 호출로 생성(개수 불일치 시 전문 번역으로 폴백). AdPane이 원문 아래 "문장별 참고 번역" 블록으로 각 문장 바로 밑에 EN·KO를 병기(문장 데이터 없는 과거 run은 기존 접이식 전문 번역으로 폴백). 하이라이트는 여전히 원문 렌더에만.
- **변경 사유**: 심사관이 문장 단위로 원문↔번역을 대조하며 위험 카드(문장 인용)와 맞춰 보기 위함. 크메르어 광고 재심사로 검증: 문장 3건 각각 EN/KO 정렬 병기 렌더 확인. KR 응답은 여전히 null(무변화).
- **보강(같은 날)**: 광고 원문 크리에이티브 안에서 **각 문장 줄 바로 아래** EN·KO 인라인 병기(`sentenceTranslationsById`, sentence_id 매핑), **위험 카드의 인용문 아래**에도 해당 문장 번역 병기(`translationForQuote`, 말줄임 인용 매칭). 하이라이트는 원문에만 유지, 크메르어 인용 카드에만 번역 표시(한국어 고지 카드는 미표시), KR·과거 run 무변화. 브라우저 검증: 원문 3문장 인라인 3/3, 위험 카드 번역 2건 렌더.

## 변경 일자: 2026-07-02 · 대상 기능: KR 라이브 심사 — 읽기/쓰기 분리 라우팅 (CC-10)
- **변경 내용**: `retriever.py`에 workspace 기반 세션 라우팅(`_session_for`) — `TEAM_NEO4J_WORKSPACES`(KR)의 코퍼스 조회(정렬 게이트·정책 컨텍스트·CU 후보·예외 closure, 전부 읽기 쿼리)는 팀 Aura로, 그 외(KH)는 기존 샌드박스로. `legal_hierarchy.py`(모법 병기 조회)도 동일 라우팅. **심사 산출물 쓰기(persistence·run_store)는 라우팅하지 않고 항상 내 샌드박스에 저장** — persistence의 코퍼스 참조는 기존 `OPTIONAL MATCH+FOREACH` 가드라 코퍼스가 없는 DB에서도 엣지만 생략하고 안전 저장.
- **변경 사유**: 팀 합의(팀 DB에 새 노드/엣지 생성 금지)를 지키면서 KR 라이브 심사를 가능하게. 검증: KR 광고("누구나 연 5% 확정 보장… 조건 없이") 정식 심사 → **reject**, 실제 KR 조문 인용(금소법 시행령 제20조 ①-3/④·감독규정 제19조), ad_translations=null(KR 경로 정상), **팀 DB 노드/엣지 수 심사 전후 완전 동일(77,702/151,908)**, KR 산출물 158노드는 내 샌드박스에 저장. test_workflow 46 pass 유지. 한계: KR 상품 대조는 상품 검색이 env(WORKSPACE_ID=KH) 고정이라 비활성(법령 축만 라이브).

## 변경 일자: 2026-07-02 · 대상 기능: 팀 공용 KR Neo4j 읽기 전용 연동 (CC-9)
- **변경 내용**: `.env`에 팀원 공용 Aura 접속키를 **별도 이름**(`TEAM_NEO4J_URI/USER/PASSWORD`, `TEAM_NEO4J_WORKSPACES`)으로 추가(내 샌드박스 `NEO4J_*`와 분리). `copilot_tools.py`의 읽기 전용 조회에 **workspace 기반 DB 라우팅** 추가 — `TEAM_NEO4J_WORKSPACES`(기본 KR workspace)에 속한 조회는 팀 DB로, 그 외(KH)는 기존 샌드박스로. 팀 DB 세션은 `NEO4J_DATABASE`(샌드박스 전용)를 쓰지 않도록 분리, KR 코퍼스의 근거 엣지 방식(`GROUNDED_IN|HAS_SOURCE_CHUNK`)도 `get_cu_detail`에 추가.
- **변경 사유**: KR 법령·금융 코퍼스(77,702 노드: CU 2,036/활성 374, PolicyHypernym 568, 상품 1,693)는 팀원 Aura에, KH PoC는 내 Aura에 분산돼 있어 그간 서로 미연결. **팀 합의("새 노드/엣지는 상호 합의 후에만 생성")에 따라 팀 DB는 읽기 전용 경로(챗 설명 도구)에만 연결** — 챗이 KR CU를 실제 조문 원문(예: 표시광고법 제1조)과 함께 설명 가능해짐. 쓰기가 발생하는 경로(심사 실행·persistence·run 스냅샷·KH 이식)는 합의 전이므로 연결하지 않음(→ 필요 시 팀에 제안).

## 변경 일자: 2026-07-02 · 대상 기능: 심사 결과 설명 챗 사이드패널 (CC-8)
- **변경 내용**: 백엔드 — 신규 `copilot_tools.py`(읽기 전용 도구 5종: `list_runs`/`get_run_detail`/`compare_runs`/`get_product_facts`/`get_cu_detail`, 전부 run 스냅샷·read-only Cypher 조회, 결과 트리밍) + `POST /api/copilot`(기존 LLMGateway 클라이언트로 function-calling 루프, 최대 6회, "도구 조회 데이터에만 근거·CU id/source_article 인용·판정 변경 불가" 시스템 프롬프트). 프론트 — 콘솔에 챗 사이드패널 `CopilotPanel.tsx`(현재 열린 run_id/workspace_id 컨텍스트 주입, "읽기 전용 · 최종 판단은 심사자" 헤더, 도구 호출 칩 표시, additive). **CopilotKit 폴백 채택**: peer deps는 React 19 호환이나 v1.62 사이드바가 자체 Node CopilotRuntime(GraphQL + 런타임 내 LLM tool-loop)을 요구해 파이썬 `/api/copilot` 단일 tool-loop 설계와 충돌 → 지시된 경량 자체 패널로 구현. 부수 수정: 심사 영속화가 만드는 병렬 엣지(run별 `review_run_id` 프로퍼티) 때문에 상품 사실 조회가 경로 곱으로 중복되던 버그를 `DISTINCT`로 수정(`product_facts.py` 선적재 로더 + copilot 도구, 567→7건).
- **변경 사유**: 심사관이 결과 화면에서 "왜 이 판정인가"를 대화로 파고들 수 있게 — 단 챗은 조회·설명만 하고 심사 실행·데이터 변경은 불가(도구 자체가 읽기 전용). KH 실제 run 4개 질문 검증: (a) 반려 사유 종합(CU id+캄보디아 조문 인용), (b) 법령/상품 축 분해, (c) run 비교(`compare_runs`+CU 상세 5회 호출), (d) 상품 사실 7건(근거 문서 인용). 조회 안 된 내용 지어내기 없음. KR 화면 additive(기존 흐름 무변화, tsc/lint/prod build 클린).

## 변경 일자: 2026-07-02 · 대상 기능: KH 평가셋·본선 데모 (CC-7)
- **변경 내용**: `data/cambodia/eval/kh_eval_v0.json`(위반 광고 2건 + 실제 PPCBank 페이지 문구 그대로의 정상 광고 2건 + 자동차대출 1건, 각 건 기대 verdict/CU/상품대조 명시) + 공식 `/api/review` 경유 러너 `run_kh_eval.py`(플래그십 크메르어 광고 3회 반복 안정성 검증, 5xx 1회 재시도). 데모 스크립트 `docs/DEMO_KH.md`(5분 시연 순서·시연 전 체크리스트·제약 명시).
- **변경 사유**: 본선 시연 전 회귀·과판정 검증 — 위반 검출만이 아니라 "정상 광고는 통과"를 실제 PPCBank 콘텐츠로 입증. 시연 리허설 절차·알려진 제약(Aura 워밍업, NBC placeholder, env 오버라이드) 문서화.

## 변경 일자: 2026-07-02 · 대상 기능: 상품 사실 선적재 대조 (CC-6)
- **변경 내용**: 신규 `ingest_cambodia_products.py`가 PPCBank Fixed Deposit/Car Loan의 ProductGroup/Product/DocumentLabel/ProductDocument(실페이지 3건, `data/cambodia/products/`+`JB_PRODUCT_DISCLOSURE_ROOT`)/페이지 검증 ProductFact 7건(+CONTAINS_FACT)을 KH workspace에 MERGE(`ingest_source=ppcbank_poc`; Product.source는 `search_products` 하드 필터(jb_data_context.py:483) 요구로 로더 상수 사용). `product_facts.analyze`에 선적재 우선 분기 추가(env `CCG_PRELOADED_PRODUCT_FACTS_WORKSPACES`, Neo4j에 사실이 있으면 PDF 온디맨드 추출 생략; env 미설정=KR은 분기 도달 불가, tests 52 pass).
- **변경 사유**: 심사마다 문서 재추출(LLM 호출) 없이 검증된 상품 사실로 즉시 대조 — 데모 안정성·비용 절감. E2E: extraction_status=PRELOADED, 대조 5/5 CONTRADICTED(기간별 차등 금리·자격요건·T&C ↔ "no conditions for everyone"; 만기지급·중도해지 미공시 ↔ "withdraw anytime with full interest"), 법령 축과 병행 표시(verdict reject). 참고: 정기예금 최소금액($500)·중도해지 0.80%는 PPCBank 공개 페이지에 없어(USD 500은 Premier Installment Deposit 소속) 의도적으로 미적재 — 페이지 원문이 근거라는 원칙.

## 변경 일자: 2026-07-02 · 대상 기능: 콘솔 관할 선택 + 참고용 번역 (CC-5)
- **변경 내용**: 백엔드 — `ReviewOutput.ad_translations{en,ko,note}`(신규 `ad_translation.py`: 판정 완료 후 단일 json_schema LLM 호출, 원문 해시 캐시, 실패 시 null, 파이프라인 불개입 — 원문만 입력; `CCG_NON_KR_LAW_WORKSPACES` 게이트, KR 응답은 null). 프론트 — ReviewForm 관할(시장) 선택(한국/캄보디아→KH workspace_id+language, CC-4 배선), AdPane 접이식 "English/한국어 (참고용 번역)" 블록 + 교차언어 "원문 표현→PolicyHypernym" 매핑 패널(ad_translations 있을 때만 렌더; 하이라이트는 원문 전용).
- **변경 사유**: 해외 광고도 한국인 심사관이 심사하므로 크메르어/영어 원문 아래 참고 번역 필요 — 단 판정은 원문 기준(번역은 표시 전용). 크메르어 E2E로 검증(응답·화면 번역, KH-CU만 발화, 캄보디아 조문만 인용); KR 화면·응답 불변(test_workflow 46 pass).

## 변경 일자: 2026-07-02 · 대상 기능: 관할·언어 엔드투엔드 배선 (CC-4)
- **변경 내용**: `ReviewInput.language`(기본 "ko", 메타데이터 전용 — 라우팅은 workspace_id 전담, 프롬프트 분기 없음) 추가, `review_input_from_payload`가 `payload.language` 수용, `server.py`의 두 `record_run` 지점이 `workspace_id`와 함께 `language`를 실행 스냅샷(파일 index + Neo4j ReviewRunSnapshot)에 보존.
- **변경 사유**: 프론트 관할 선택→백엔드 라우팅→실행 기록(대시보드 재실행)의 연결 고리. 기본값이면 기존 동작과 동일(KR 회귀 없음, test_workflow 46 pass). E2E: `{workspace_id: KH, language:"en"}` 심사에서 KH-CU만 발화·캄보디아 조문만 인용·스냅샷에 ws+lang 보존 확인.

## 변경 일자: 2026-07-01 · 대상 기능: 판정 근거 관할 분리 (CC-3)
- **변경 내용**: `utils.uses_korean_law_context(workspace_id)`(env `CCG_NON_KR_LAW_WORKSPACES`, 기본=모든 workspace 한국법 유지) 신설 후 분기 — `judge.py`(비-KR이면 프롬프트에 한국법 예시 무효화 오버라이드 append), `policy_evidence.py`(한국법 `DELEGATES_TO` 위임 엣지 생략), `router.py`(현저성 이슈의 하드코딩 `금소법 제22조` 제거). `workflow.py`가 workspace_id 전달.
- **변경 사유**: KH 판정 근거 설명에 하드코딩된 한국법 조문이 섞여 나오는 누출 차단. 적용 후 KH 심사의 legal_basis/detected_issues는 캄보디아 조문만 인용(한국법 토큰 134→11, 잔여분은 캄보디아 Art.18의 한국어 표기 + 별도 유보된 고지 카탈로그). KR 프롬프트·경로는 바이트 동일(test_workflow 46 pass).

## 변경 일자: 2026-07-01 · 대상 기능: 정렬층 준비 게이트 workspace화 (CC-3)
- **변경 내용**: `retriever.py` `alignment_min_thresholds()` — 준비 게이트 임계값을 env로 설정 가능화(전역 `CCG_MIN_HYPERNYM`/`CCG_MIN_PREMISE` + workspace별 `CCG_MIN_*_<ws>`, 우선순위 per-ws>전역>기본 30/100). 품질 게이트(link ratio ≥0.80)는 비설정 유지, 음수/0 오버라이드는 기본값 폴백. `.env`에 KH 10/15 설정.
- **변경 사유**: KR 대형 코퍼스 기준 하드코딩(30/100)에 16-CU KH PoC(13/19)가 막혀 심사 진입 불가 → workspace 규모별 임계값 필요. 조정 후 KH 정식 심사 첫 통과(reject: KH-CU-16/04 NON_COMPLIANT, Sub-Decree 232 + 소비자보호법 Art.23-27 근거). KR 기본값·게이트 불변 — 4-렌즈 어드버서리 검증으로 회귀 없음 증명(20만 입력 predicate 동일, Cypher 바이트 동일).

## 변경 일자: 2026-07-01 · 대상 기능: KH 정렬층 컴파일 (CC-2 step 3)
- **변경 내용**: `policy_compiler.py --workspace-id <KH> --batch-size 16` 실행 — PolicyHypernym 13(한국어 정규 라벨, 설계 의도)·Premise 19·CUEmbeddingProfile 16·CULegalElementProfile 16 생성(16/16 CU 커버), 벡터 인덱스 2종 ONLINE.
- **변경 사유**: KH CU 위에 검색·게이팅용 정렬층 구축(기존 컴파일러 그대로 사용, 코드 무수정). 격리 유지(101 KH 노드, KR 0).

## 변경 일자: 2026-07-01 · 대상 기능: KH 법령 코퍼스 적재 (CC-2)
- **변경 내용**: 신규 `ingest_cambodia.py`(기존 KR 적재기 무수정)로 ComplianceUnit 16건(principle은 KR 어휘 설명의무/광고규제, 본문 영어)·LegalClause 14건·LegalChunk 7건·근거 엣지 29건(GROUNDS_CU/EVIDENCES_CU)을 KH workspace에 멱등 MERGE. 근거: 소비자보호법 2019(Art. 9–27, 원문 PDF에서 추출) + Sub-Decree 232/Prakas 249(DFDL 영문 요약, 2차 자료 명시). 전 노드 `effective_date/version/source_date` + `poc=true, lawyer_verified=false`.
- **변경 사유**: 캄보디아 규제를 동일 그래프 스키마의 신규 관할 데이터로 이식 — 파이프라인 코드 재작성 없이 workspace 격리로 KR/KH 분리. 날짜/버전 필드는 향후 규제 개정 추적·감사의 토대. NBC 금리상한은 원문 미확보(403)로 citation-only placeholder.

---

**미결/알려진 한계**: ① 상품 검색 workspace가 env(`WORKSPACE_ID`) 기반 — KR·KH 혼합 단일 배포엔 per-review 스레딩 필요, ② NBC 규정 원문 미확보(KH-CU-05 placeholder), ③ KH 코퍼스 전체가 캄보디아 법률 전문가 검증 전(PoC), ④ 고지 카탈로그는 한국어 기반 유지(KH 필수고지는 별도 과제).
