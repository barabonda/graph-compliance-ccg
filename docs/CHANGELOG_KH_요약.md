# 기능 변경이력 요약 — 캄보디아(KH) 관할 확장

> 기능명세서 7장(기능 변경이력)에 그대로 옮길 수 있는 표. 상세는 `CHANGELOG_FEATURES.md`.
> 공통 격리 키: `workspace_id = graphcompliance_cambodia_ppcbank_20260630` (KR 데이터·경로 불변)

| 변경 일자 | 대상 기능 | 변경 내용 | 변경 사유 |
|---|---|---|---|
| 2026-07-01 | 법령 코퍼스 적재 (CC-2) | 신규 `ingest_cambodia.py`로 캄보디아 소비자보호법(2019)·Sub-Decree 232/Prakas 249 근거 ComplianceUnit 16건, LegalClause 14건, LegalChunk 7건, 근거 엣지 29건을 KH workspace에 적재. 전 노드에 `effective_date/version/source_date` 부착 | 캄보디아 규제를 기존 그래프 스키마 그대로 신규 관할로 이식(코드 수정 없는 데이터 확장). 날짜 필드는 향후 개정 추적·감사 기반 |
| 2026-07-01 | 정책 정렬층 컴파일 (CC-2) | `policy_compiler.py --workspace-id <KH>` 실행으로 PolicyHypernym 13·Premise 19·CUEmbeddingProfile 16·CULegalElementProfile 16 생성, 벡터 인덱스 ONLINE | KH CU 위에 검색·게이팅용 정렬층(개념사전·임베딩) 구축 |
| 2026-07-01 | 정렬층 준비 게이트 (CC-3) | `retriever.py`에 `alignment_min_thresholds()` 신설 — 임계값을 env(전역 `CCG_MIN_HYPERNYM`/`CCG_MIN_PREMISE` + workspace별 `CCG_MIN_*_<ws>`)로 설정 가능화. KR 기본 30/100·품질 게이트(link ratio ≥0.80) 불변, 음수/0 오버라이드 무시 | KR 대형 코퍼스 기준 하드코딩 임계값(30/100) 때문에 소규모 KH PoC(13/19)가 심사 진입 불가 → workspace 규모별 조정 필요 |
| 2026-07-01 | 판정 근거 관할 분리 (CC-3) | `utils.uses_korean_law_context()` (env `CCG_NON_KR_LAW_WORKSPACES`) 신설, `judge.py`(프롬프트 한국법 예시 무효화)·`policy_evidence.py`(한국법 위임 엣지 생략)·`router.py`(금소법 제22조 하드코딩 분기) 적용 | KH 판정 근거에 하드코딩된 한국법 조문(금소법 등)이 섞여 나오는 누출 차단 — 캄보디아 조문만 인용되도록. KR 프롬프트는 바이트 동일 |
| 2026-07-02 | 관할·언어 배선 (CC-4) | `ReviewInput.language`(기본 "ko", 메타데이터 전용) 추가, `review_input_from_payload` 배선, `record_run` 스냅샷(파일+Neo4j)에 `workspace_id`/`language` 보존 | 프론트 관할 선택→백엔드 라우팅→실행 기록 보존의 엔드투엔드 연결(대시보드 재실행 지원). 판정 라우팅은 workspace_id가 전담 |
| 2026-07-02 | 콘솔 관할 선택 + 참고 번역 (CC-5) | 프론트: 관할(시장) 선택(한국/캄보디아), 비-KR 결과 화면에 접이식 영어·한국어 참고 번역 블록 + 교차언어 개념 매핑 패널. 백엔드: `ad_translations{en,ko,note}` 필드(신규 `ad_translation.py`, 판정 완료 후 생성·해시 캐시·실패 시 null) | 해외 광고도 한국인 심사관이 심사 — 원문 아래 참고 번역 필요. 번역은 표시 전용으로 판정 파이프라인에 불개입(원문 기준 심사 원칙). KR 화면·응답 불변 |
| 2026-07-02 | 상품 사실 선적재 (CC-6) | 신규 `ingest_cambodia_products.py`로 PPCBank 정기예금·자동차대출 Product/ProductDocument(실페이지 3건)/페이지 검증 ProductFact 7건 적재. `product_facts.analyze`에 선적재 우선 분기(env `CCG_PRELOADED_PRODUCT_FACTS_WORKSPACES`) — Neo4j에 사실이 있으면 PDF 재추출 생략 | 심사마다 문서 재추출(LLM) 없이 검증된 상품 사실로 즉시 대조 — 데모 안정성·비용 절감. 페이지에 없는 값(최소금액·중도해지율)은 미적재(원문 근거 원칙). KR 경로 불변 |
| 2026-07-02 | KH 평가셋·데모 (CC-7) | `data/cambodia/eval/kh_eval_v0.json`(위반 2건 + 실제 PPCBank 문구 기반 정상 2건 + 대출 1건, 기대값 포함) + 러너 `run_kh_eval.py`(공식 API 경유, 플래그십 3회 반복 안정성 검증), 데모 스크립트 `docs/DEMO_KH.md` | 본선 시연 전 회귀·과판정 검증("정상 광고는 통과") 및 시연 절차·제약 문서화 |
| 2026-07-03 | Claude 상품 사실 그래프 확장 (CC-12) | 신규 `build_ppcbank_product_graph.py`(크롤 → Claude Opus 4.8 **영어** 추출 → KH MERGE → 검증)로 PPCBank 상품 **20종**(예금10·대출7·카드3)·문서 21건에서 **ProductFact 255건** 적재(CC-6 수기 7건 대체, `extraction_method=claude:claude-opus-4-8`; 미공시는 `*_disclosure` 사실로도 기록). 라이브 파이프라인은 OpenAI 그대로(오프라인 적재만 Claude), 키는 `.env ANTHROPIC_API_KEY`(gitignore) | 상품 사실 그래프를 2종→20종으로 확장(대회 Claude API 이용권, 실사용 ~$1, 정확도 우선). 격리 0·KR/팀DB 무변경(쓰기는 샌드박스만), 신상품 E2E(Home Loan 위반 광고) `PRELOADED`·대조 CONTRADICTED5/CONDITION_MISSING2/PROMINENCE1 검증 |

**미결/알려진 한계**: ① 상품 검색 workspace가 env 기반(`WORKSPACE_ID`)이라 KR·KH 혼합 단일 배포에는 per-review 스레딩 필요, ② NBC 금리상한 원문 미확보(citation-only placeholder), ③ 전체 KH 코퍼스는 캄보디아 법률 전문가 검증 전(PoC), ④ 고지 카탈로그(`disclosure_catalog.py`)는 한국어 기반 유지(KH 고지는 별도 과제).
