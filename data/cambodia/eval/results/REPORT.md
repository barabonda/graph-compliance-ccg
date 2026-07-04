# KH eval v0 — 결과 리포트 (2026-07-02)

7회 심사(공식 `/api/review`, KH workspace). 원시 응답: `results/*.json`, 요약: `_summary.json`.

## 기대 vs 실제

| 항목 | 기대 verdict | 실제 | 발화 CU | 상품 대조 | 번역 | 캄보디아 조문만 |
|---|---|---|---|---|---|---|
| 01 크메르어 위반 ×3 | reject | **reject / reject / revise** | 16·07·02(±01/04/05) — NON_COMPLIANT 3/3회 검출 | PRELOADED · CONTRADICTED(+CONDITION_MISSING) | en+ko 3/3 | ✅ 3/3 |
| 02 영어 위반 | reject | **reject** ✅ | 16·07 NON_COMPLIANT | PRELOADED · CONTRADICTED 5건 | en+ko | ✅ |
| 03 실제 페이지 문구(정상 기대) | pass_candidate | **revise** ❌ 과판정 | KH-CU-03(0.78)·04(0.74) NON_COMPLIANT | PRELOADED · SUPPORTED+CONDITION_MISSING | en+ko | ✅ |
| 04 실제 프로모션(정상 기대) | pass_candidate | **needs_review** ⚠️ | NON_COMPLIANT 0건 (INSUFFICIENT만) | PRELOADED · SUPPORTED+PROMINENCE_INSUFFICIENT | en+ko | ✅ |
| 05 자동차대출 실제 문구 | pass±needs_review | **needs_review** ✅(예상 범위) | NON_COMPLIANT 0건 | NO_PRODUCT_DOCUMENT(예상대로 — Car Loan 선적재 사실 없음) | en+ko | ✅ |

## 안정성 (플래그십 3회)

- verdict: reject 2/3, revise 1/3 — **완전 안정 아님**. 단, 3회 모두 NON_COMPLIANT 검출 + 차단성 판정(reject/revise 모두 게시 불가) → **"위반 검출" 기준으로는 3/3**.
- 원인: reject 경계가 `NON_COMPLIANT score ≥ 0.82`(router.py:35) — run3은 최고 score가 경계 아래.

## 과판정 상세 (숨김 없이)

**03 (페이지 원문 "The longer you commit... the higher the interest rate will be"): revise**
- KH-CU-03 (0.78): "'will be' 확정 단정 + 구체 조건·변동 가능성 미제시 → 무조건적 고수익 오인 우려" (근거: CPL Art.24, Sub-Decree 232)
- KH-CU-04 (0.74): "'specific interest rate depending'이라 하면서 그 조건(기간/금액/구간)이 광고에 없음 → 최소정보 누락" (CPL Art.23·24·27)
- 해석: 발췌가 **금리표를 떼고 문구만** 가져와서, 단독 광고로 보면 '조건 있음'만 말하고 구체 조건이 없는 상태 — 판정 논리 자체는 일관됨. 전체 페이지(금리표 포함)를 그대로 광고로 넣으면 결과가 달라질 수 있음(미검증).

**04 (프로모션 "up to 5.14% ... via Mobile App or smartBiz, May 1–15"): needs_review**
- 위반 단정 없음. 조건 고지가 혜택 대비 현저성 부족(PROMINENCE_INSUFFICIENT) + Track B MEDIUM(0.68) → 심사관 회부.
- 해석: "시스템이 단정하지 않고 사람에게 넘긴다"는 사전심의 보수 동작 — 위반 오탐이 아니라 회부.

## 교차언어 정규화 (크메르어 → 한국어 정책개념, run1)

- "អត្រាការប្រាក់ខ្ពស់បំផុត"(최고 금리) → 절대적·최상급 표현 사전 확인 / 허위·기만 금지 / 오인·오도 금지
- "ដោយគ្មានលក្ខខណ្ឌ"(조건 없이) → 조건부 이익·금리 명확 표시 의무 / 허위·기만 금지
- "ការប្រាក់ពេញ"(이자 전액) → 허위·기만 금지 / 조건부 표시 의무

## 공통 확인

- **한국법 조문 인용: 7/7회 0건** (판정 근거·이슈 모두 캄보디아 조문만)
- **번역 생성: 7/7** (en+ko)
- **선적재 대조: 예금 6/6회 PRELOADED**, 자동차대출은 선적재 없음 → 예상대로 문서 대조 생략
- 소요: 회당 103~131초

## 추가 실험 (2026-07-02) — (b)안: 금리표 포함 전문 재심사 (`kh-eval-03b`)

③의 발췌에 같은 페이지의 **금리표(기간·통화·채널, 만기/월지급 표 전체)와 자격요건(Requirements)**까지 붙인 전문(2,122자)으로 재심사:

- **verdict: `needs_review`** (③ revise → 개선). **NON_COMPLIANT 0건** — 판정 전부 INSUFFICIENT/NOT_APPLICABLE(최고 score 0.45). Track B MEDIUM(0.68).
- 상품 대조: PRELOADED, SUPPORTED 10 / NO_PRODUCT_FACT 11 / PROMINENCE_INSUFFICIENT 1 / CONTRADICTED 1. 번역 en+ko, 한국법 인용 0.
- **공시 충실도 그래디언트 확인**: 위반 광고 → reject / 조건 언급만(구체 조건 없음) → revise / 금리표·자격요건 포함 전문 → needs_review(위반 단정 소멸). 판정이 공시 수준에 단조 반응 = 근거 기반 판정의 증거.
- pass_candidate엔 미달 → **데모 ⑤는 (a)안 채택**: `kh-eval-04` 프로모션을 "무단정·심사관 회부 = 사전심의 도구의 올바른 동작, 최종 결정은 심사자" 내러티브로 시연(DEMO_KH.md ⑤ 갱신 완료).

## 데모 시사점 (결정 반영)

1. ⑤단계 = **(a)안 확정**: kh-eval-04(실제 프로모션, NON_COMPLIANT 0건·needs_review)를 회부 내러티브로 시연. 보조 멘트로 위 그래디언트(reject→revise→needs_review) 활용.
2. 플래그십은 reject가 2/3이므로 시연 전 리허설 1회로 당일 결과 확인 권장(revise여도 '차단' 스토리는 성립).
