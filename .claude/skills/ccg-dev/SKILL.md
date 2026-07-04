---
name: ccg-dev
description: "JB Compliance(graph-compliance-ccg) 기능 개발 오케스트레이터. 심사 콘솔/파이프라인/코파일럿/대시보드에 기능 추가, 수정, 개선, 버그 수정, 리팩터링 요청 시 반드시 이 스킬로 에이전트 팀을 조율. 후속 작업 — 다시 실행, 재실행, 업데이트, 보완, 이전 결과 개선, '백엔드만/프론트만 다시', 'QA만 다시 돌려줘' 요청에도 반드시 이 스킬을 사용. 단순 질문·코드 읽기는 직접 응답 가능."
---

# CCG Feature Dev Orchestrator

graph-compliance-ccg의 기능 개발을 백엔드·프론트·QA 에이전트 팀으로 수행하는 통합 스킬.
리더(메인 세션)가 팀을 조율한다.

## 실행 모드: 하이브리드

| Phase | 모드 | 이유 |
|-------|------|------|
| Phase 2 (구현) | 에이전트 팀 (병렬 + SendMessage) | 경계면 계약을 실시간 공유해야 함 |
| Phase 3 (QA) | 서브 에이전트 (단독) | 독립 검증 — 구현자와 분리된 시각 |

## 에이전트 구성

| 팀원 | 정의 파일 | 타입 | 스킬 | 산출물 |
|------|----------|------|------|--------|
| ccg-backend-dev | `.claude/agents/ccg-backend-dev.md` | general-purpose | ccg-backend | 코드 + `_workspace/{NN}_backend_summary.md` + `contract_api.md` |
| ccg-frontend-dev | `.claude/agents/ccg-frontend-dev.md` | general-purpose | ccg-frontend | 코드 + `_workspace/{NN}_frontend_summary.md` |
| ccg-qa | `.claude/agents/ccg-qa.md` | general-purpose | ccg-qa-verify | `_workspace/{NN}_qa_report.md` |

모든 Agent 호출에 `model: "opus"`를 명시한다.
에이전트 프롬프트에는 반드시 (1) 해당 에이전트 정의 파일을 먼저 읽으라는 지시,
(2) 담당 스킬 경로, (3) 기능 명세, (4) `_workspace/` 경로를 포함한다.

## 워크플로우

### Phase 0: 컨텍스트 확인 (후속 작업 지원)

`_workspace/` 존재 여부로 실행 모드를 결정한다:

- **미존재** → 초기 실행. Phase 1로.
- **존재 + 부분 수정 요청** (예: "백엔드만 다시", "QA만") → 부분 재실행.
  해당 에이전트만 재호출하고, 프롬프트에 이전 산출물 경로를 포함해 기존 결과를
  읽고 피드백을 반영하게 한다.
- **존재 + 새 기능 요청** → 새 실행. 기존 `_workspace/`를
  `_workspace_prev_{YYYYMMDD}/`로 이동 후 Phase 1로.

### Phase 1: 준비 (리더 직접)

1. 요청을 분석해 백엔드/프론트 작업 범위를 나눈다. 어느 한쪽만 필요한 기능이면
   해당 에이전트만 투입한다 (불필요한 팀원 생성 금지).
2. `_workspace/00_input/spec.md`에 기능 명세를 기록: 목표, 범위(백/프론트), 수용 기준.
3. 경계면이 걸리는 기능이면 API 계약 초안을 `_workspace/contract_api.md`에 작성.
4. TaskCreate로 작업 목록 등록 (구현 작업 + QA 작업, QA는 구현에 의존).

### Phase 2: 구현

**실행 모드:** 에이전트 팀 (병렬)

1. 단일 메시지에서 ccg-backend-dev와 ccg-frontend-dev를 동시 스폰
   (`run_in_background: true`, `model: "opus"`).
2. 통신 규칙:
   - 백엔드가 API shape을 확정/변경하면 `contract_api.md` 갱신 후 SendMessage로
     프론트에 통지
   - 프론트가 계약 불일치를 발견하면 백엔드에 SendMessage로 확인
   - 명세 모호 → 리더에게 질문 (리더는 필요 시 사용자에게 AskUserQuestion)
3. 리더는 완료 통지를 기다리며, 각 에이전트의 summary 파일을 Read로 수집한다.

### Phase 3: QA (incremental)

**실행 모드:** 서브 에이전트

1. **한쪽 모듈이 먼저 완성되면 기다리지 말고 즉시** ccg-qa를 스폰해 해당 모듈 +
   경계면을 검증시킨다 (경계면 버그의 조기 발견이 목적).
2. QA 리포트의 실패 항목은 담당 에이전트에게 SendMessage로 수정 요청
   (경계면 이슈는 양쪽 모두에게).
3. 수정 → 해당 항목만 재검증. 같은 항목 2회 실패 시 리더가 직접 개입하거나
   사용자에게 보고.
4. 전체 완료 후 최종 QA 1회: pytest + tsc + (env 가능 시) review_ad 스모크.

### Phase 4: 통합 보고 및 정리

1. 산출물 수집: summary 2종 + qa_report.
2. 사용자 보고: 구현 내용, 테스트 결과(통과/실패/미검증 구분), 남은 리스크.
3. `_workspace/`는 보존한다 (감사 추적·부분 재실행용). 커밋은 사용자가 요청할 때만.
4. 하네스 개선 피드백 기회를 제공한다 (강요하지 않음).

## 데이터 흐름

```
[리더] → spec.md ─┬→ [ccg-backend-dev] ──→ contract_api.md ──→ [ccg-frontend-dev]
                  │        │      ↑ SendMessage(계약 변경/질의) ↓      │
                  │        └──→ backend_summary.md    frontend_summary.md
                  │                    │                       │
                  └──── (모듈 완성 즉시) → [ccg-qa] ← ──────────┘
                                           │ qa_report.md (실패 → 양쪽에 수정 요청)
                                           ↓
                                    [리더: 통합 보고]
```

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| 에이전트 1명 실패/무응답 | SendMessage로 상태 확인 → 1회 재스폰. 재실패 시 리더가 직접 수행하거나 누락 명시 |
| pytest/tsc 실패 반복(2회+) | 담당 에이전트 재시도 중단, 리더 개입 또는 사용자 보고 |
| env 부재로 스모크 불가 | 실행하지 않고 필요한 env 목록과 함께 "미검증" 보고 — 이 프로젝트는 자격증명 부재 시 실패가 정상 계약 |
| 경계면 계약 충돌(백↔프론트 이견) | 리더가 server.py 실제 코드를 기준으로 판정, 양쪽에 통지 |
| 명세 모호 | 임의 결정 금지 — AskUserQuestion으로 사용자 확인 |

## 테스트 시나리오

### 정상 흐름
1. 사용자: "위험 카드에 근거 조문 미리보기 툴팁 추가해줘"
2. Phase 1: spec.md 작성 — 백엔드는 `/api/review` 응답에 조문 원문 필드 추가,
   프론트는 위험 카드 툴팁 렌더링. contract_api.md 초안 작성.
3. Phase 2: 두 에이전트 병렬 구현, 백엔드가 필드명 확정 → 프론트에 통지.
4. Phase 3: 백엔드 완성 즉시 QA가 응답 shape ↔ types.ts 교차 검증, pytest·tsc 실행.
5. Phase 4: 통과/미검증 구분한 보고. `_workspace/` 보존.

### 에러 흐름
1. Phase 3에서 QA가 발견: 백엔드는 `clause_text`(snake), 프론트 types.ts는
   `clauseText`(camel) — 런타임 undefined.
2. QA가 양쪽 에이전트에 수정 요청 (기준: server.py 실제 응답).
3. 프론트가 types.ts 수정 → QA가 해당 항목만 재검증 → 통과.
4. 최종 보고에 발견·수정 이력 포함.
