---
name: ccg-guideline-synth
description: "graph-compliance-ccg 합성 평가 데이터 생성·라벨 가이드. 금융광고규제 가이드라인/은행 광고심의 기준에서 추출한 위반 패턴 카탈로그(eval/violation_taxonomy_v0_2.json + references/violation_catalog.md)를 근거로 준수광고를 위반으로 변이시켜 정답 라벨을 확정하고, 라이브 심사로 정밀도·재현율을 산출한다. '합성 데이터', '평가셋 만들어', '위반 사례 생성', '택소노미', '정밀도 재현율', '평가 데이터 라벨', 'JB 실제 광고 평가', '평가 로그' 요청 및 후속 보완·재실행 요청 시 반드시 이 스킬을 사용."
---

# CCG 합성 평가 데이터 생성 가이드

가이드라인 원문에서 추출한 **위반 패턴 카탈로그**를 근거로, ProductFact에 기반한
준수광고를 위반으로 변이시켜 **정답 라벨이 확정된** 평가 데이터를 만든다. 그리고
그 데이터를 라이브 심사 파이프라인에 통과시켜 **정밀도·재현율**을 산출한다.

## 핵심 규율 (위반 금지)

1. **자기충족 평가 금지** — 변이 지시문(`mutation_instruction`)은 **가이드라인·심의
   기준 원문에서만** 도출한다. 우리 검출 코드(`rule_judgment.py`, `judge.py`,
   `overall_impression.py`, `disclosure_catalog.py`)를 읽고 역산해 패턴을 만들지 마라.
   검출 룰에 맞춰 변이를 설계하면 평가가 자기 자신을 채점하게 된다.
2. **정답 라벨은 변이 시점에 확정** — 라벨(violation_types, articles, risk_level,
   required_disclosures, expected_routing)은 카탈로그 패턴에서 **생성 시점에** 결정된다.
   심사 결과를 보고 라벨을 고치지 마라(사후 라벨링 금지).
3. **ProductFact 근거 준수광고가 출발점** — 클린 광고는 실제 상품문서에서 추출한
   ProductFact에서만 생성한다. 없는 금리·조건·혜택을 지어내지 않는다.
4. **룰/LLM 역할 분리 유지** — 카탈로그의 `category`가 `required_disclosure_missing`/
   `misleading_scope` 등 기계적 위반이면 룰이 잡아야 하고, `guarantee_or_return_misleading`/
   `prohibited_expression` 등 맥락 위반이면 LLM(Track B 종합인상)이 잡는다. 카탈로그는
   이 분리를 반영하되, 어느 경로가 잡는지를 변이에 반영하지 않는다(자기충족 금지와 동일).
5. **보험 전용 패턴은 생성 제외** — `product_groups: []`(보험)·`["investment"]`은
   예금/대출 상품 그래프로 생성되지 않는다. 카탈로그에는 원문 근거와 함께 남긴다.

## 카탈로그 (정답 라벨 소스)

- `eval/violation_taxonomy_v0_2.json` — 스키마는 v0.1과 호환(`codes[]`). 각 코드:
  - `code`(=pattern_id), `type`(이자율수익률/산정방법/대출/부수혜택/보험/금지행위/
    의무표시누락/준수사항/하드케이스), `product_groups`, `channels`, `category`,
    `action_type`, `required_positive_features`
  - 원문 출처: `source_document`, `source_article`, `source_quote`(가이드라인/심의기준
    원문 인용), `origin`
  - gold 라벨: `articles`, `sales_principles`, `required_disclosures`, `risk_level`,
    `expected_routing`
  - 변이 제어: `mutation_instruction`(원문에서 도출), `mutation_phrase`(템플릿 폴백),
    `gold_span_hint`
- `references/violation_catalog.md` — 패턴별 원문 인용 전문. 출처 조항 대조용.
- 원문 소스(추출 근거, 창작 금지):
  - `.../금융광고 심의 데이터셋/별첨자료_금융광고규제가이드라인.md` (참고2 5유형 부당사례,
    참고3 판단사례; 이미지 페이지는 PyMuPDF 렌더 후 비전)
  - `.../은행_광고심의_기준_및_세칙_검증수정본.md` (§16 의무표시 / §17 금지사항 / §18 준수사항)
  - `eval/regulator_cases_full.jsonl` (참고3 완결 사례 4건 — 스타일 참조)

## 두 평가 트랙

### Track A — 합성 gold (정밀도·재현율)
정답 라벨이 있으므로 정밀도·재현율을 계산한다. 카탈로그 변이로 만든 위반 + 미변이
클린(대조군)을 라이브 심사에 통과시키고 유형별·상품군별로 분해한다.

### Track B — JB 실제 광고 로그 (`05_jbbank`)
`/Users/barabonda/Downloads/05_jbbank/artifacts/*`는 Upstage document-parse로 OCR한
전북은행 실제 광고물(이미지+글). **정답 라벨이 없다** → 정밀도·재현율 대신 심사 로그
(판정 분포·검출 이슈·플래그된 광고)를 산출하고 운영 대시보드 평가 탭에 남긴다.
각 심사는 `run_store.record_run`으로 영속화되어 `/api/runs`·`/api/eval/reports`로 조회된다.

## 실행 명령

프로젝트 루트: `/Users/barabonda/Documents/GraphRAG/examples/graph-compliance-ccg`
env(OPENAI_API_KEY/ANTHROPIC_API_KEY/NEO4J_*)가 없으면 생성·심사는 **실패해야 정상**
(결정론 fallback 금지). 미검증으로 처리하고 필요한 env를 보고한다.

### Track A: 합성 생성 → 품질검사 → 라이브 → 지표
```bash
# 1) 생성 (v0_2 카탈로그, 상품·채널·조합당 코드 수 제한으로 총량 통제)
python3 build_synthetic_eval_dataset.py \
  --taxonomy eval/violation_taxonomy_v0_2.json \
  --product "JB 참 괜찮은 정기예금" --product "도전 루틴 적금" \
  --product-group deposit --channels web_page,sns \
  --codes-per-combo 6 \
  --output eval/synth_v0_2_deposit.jsonl

# 2) 생성 품질 검사 (span/라벨/ProductFact 정합성; 실패 시 재생성)
python3 quality_report_synthetic_eval_dataset.py \
  --input eval/synth_v0_2_deposit.jsonl --output eval/synth_v0_2_quality.json --fail-on-errors

# 3) 라이브 심사 + 지표 (정답 라벨은 워크플로에 주입되지 않음)
python3 evaluate.py --input eval/synth_v0_2_all.jsonl --run-live --workers 3 \
  --save-predictions eval/synth_v0_2_pred.jsonl --output eval/synth_v0_2_metrics.json

# 4) 유형별·상품군별 분해 (evaluate.py 재사용)
python3 eval/synth_v0_2_breakdown.py \
  --records eval/synth_v0_2_all.jsonl --predictions eval/synth_v0_2_pred.jsonl \
  --taxonomy eval/violation_taxonomy_v0_2.json --output eval/synth_v0_2_report.md
```

### Track B: JB 실제 광고 라이브 심사 + 로그 영속화
```bash
python3 eval/run_jbbank_eval.py \
  --artifacts-dir "/Users/barabonda/Downloads/05_jbbank/artifacts" \
  --product-groups deposit,loan --limit 40 --workers 3 \
  --report eval/jbbank_eval_report.json
# → 각 심사는 run_store에 영속(source_type=jbbank_eval), 배치 리포트는 eval/에 기록되어
#   운영 대시보드 평가 탭(/api/eval/reports)에서 조회된다.
```

## 총량·시간 통제 (반드시 준수)

- **라이브 실행 총량(Track A + Track B)이 120건을 초과하면 시작 전에 리더에게 보고**하고
  확인을 받는다. 각 심사는 다중 LLM 호출(룰→그래프→개별판정→종합인상)로 수십 초 걸린다.
- `--codes-per-combo`(Track A)·`--limit`(Track B)로 총량을 통제한다. 상품×채널 조합마다
  적용 코드를 **결정론적으로 회전 선택**하므로 상품 간 패턴 커버리지가 균형을 이룬다.
- 위반 스윕(pilot50 등)이 종료된 뒤에만 라이브 API를 자유롭게 쓴다.

## 품질 검사 절차 (생성 직후)

`quality_report_synthetic_eval_dataset.py`가 검사하는 blocking 오류:
- 중복 id, `expected_problem_spans`가 본문에 verbatim 부재(SPAN_NOT_IN_TEXT),
  violation=true인데 violation_types 없음, ProductFact source_document 미선택,
  evidence_text 없음, confidence 범위 밖.
- blocking 오류가 있으면 **해당 레코드를 재생성**한 뒤에만 라이브로 넘어간다.

## 지표 해석 (evaluate.py)

- `predicted_violation` = `final_verdict ∈ {reject, revise}` (needs_review는 위반 아님).
- `violation_precision`/`violation_recall` = gold `violation` 대비 이진 지표.
- `article_metrics` = canonical 조문(위임사슬 계열) 멀티라벨 micro/macro F1·F2·MCC.
- 클린 대조군의 `clean_non_pass_rate`·`overblocking_rate`로 과차단(오탐)을 확인한다.
- Track B(실제 광고)는 gold가 없으므로 **정밀도·재현율을 계산하지 않는다** —
  판정 분포·검출 이슈 로그만 보고하고 "gold 부재"를 명시한다.

## 산출물 규약

- 카탈로그/스킬 변경은 리더가 CLAUDE.md 이력에 기록(에이전트가 직접 CLAUDE.md 수정 금지).
- API 응답 shape이 바뀌면 `_workspace*/contract_api.md` 갱신 후 프론트에 통지.
- git 커밋 금지(리더 지시 없으면).
