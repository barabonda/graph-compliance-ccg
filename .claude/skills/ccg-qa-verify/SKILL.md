---
name: ccg-qa-verify
description: "graph-compliance-ccg 변경 검증 가이드. 기능 구현 후 QA, 경계면(백엔드↔프론트) 정합성 검사, pytest/tsc 실행, review_ad 심사 품질 스모크, 회귀 확인 요청 시 반드시 이 스킬을 사용. '검증해줘', 'QA 돌려줘', '깨진 데 없나 확인' 요청 포함."
---

# CCG QA 검증 가이드

핵심 원칙: **존재 확인이 아니라 교차 비교**. 생산자와 소비자 코드를 **동시에 열어**
계약이 맞는지 대조한다. 각각 따로 보면 둘 다 "정상"이다.

## 1. 경계면 교차 비교 (최우선)

| 검증 대상 | 생산자 (왼쪽) | 소비자 (오른쪽) |
|----------|--------------|----------------|
| 심사 응답 shape | `server.py` `/api/review`·`/api/review/stream` 반환 객체 | `frontend/src/lib/types.ts` + `hooks/useReview.ts` |
| 실행 기록 shape | `run_store.py` + `/api/runs` 응답 | 대시보드 컴포넌트가 읽는 필드 |
| 코파일럿 응답 | `/api/copilot`, `/copilot-agent` | `lib/copilotContext.ts`, `components/copilot/` |
| 판정 카테고리 키 | 백엔드 판정 결과의 원칙/카테고리 문자열 | `lib/labels.ts` PRINCIPLE_COLORS 매칭 키 |
| 프록시 경로 | `frontend/src/app/api/*` 프록시 라우트 + `next.config` rewrite | `server.py` 실제 엔드포인트 존재 여부 |
| workspace 라우팅 | `labels.ts` BANKS의 workspaceId | 백엔드가 인식하는 workspace_id 값 |

절차 (변경된 경계면만):
1. 백엔드에서 실제 `json()` 반환/스트림 이벤트 객체의 필드를 추출한다.
2. 프론트 타입 정의와 실제 접근 필드(`data.xxx`)를 추출한다.
3. 필드명(snake/camel), 래핑(`{items: []}` vs 배열), 옵셔널 처리를 대조한다.
   **생산자에만 있고 소비자 타입에 없는 필드도 드리프트로 기록한다** — 지금은 무해해도
   소비 시작 시점에 조용히 누락된다 (예: 다국어 확장에서 `language` 필드).
4. 스트림 응답은 이벤트별 shape이 다르다 — 이벤트 타입별로 각각 대조한다.
   스트림 추적 경로: 프론트 훅 → `frontend/src/app/api/review/stream/route.ts` 프록시 →
   `server.py` `/api/review/stream` 순으로 따라간다.

주의 패턴: 제네릭 캐스팅(`fetchJson<T>`)은 런타임 불일치를 못 잡는다. tsc 통과를
경계면 통과로 착각하지 마라.

## 2. 테스트 실행

```bash
# 백엔드 (프로젝트 루트에서)
python3 -m pytest tests/ -q

# 프론트
cd frontend && npx tsc --noEmit
```

pytest 실패 발견 시 먼저 **스텁 기반인지 라이브 의존인지 판별**한다: FakeLLM/FakeRetriever
등 결정론 스텁 기반 실패는 환경과 무관한 **확정 회귀(실패)**다. LLM/Neo4j 연결이 필요한
테스트의 실패만 환경 문제일 수 있다. 스텁 기반 실패를 "미검증"으로 뭉개지 마라.

## 3. 심사 품질 스모크 (환경 있을 때)

env(OPENAI_API_KEY 또는 ANTHROPIC_API_KEY, NEO4J_URI/USER/PASSWORD)가 설정된 경우:

```bash
python3 review_ad.py --text "지난 3년간 조기상환 성공률이 높았던 ELS, 중위험 투자자에게 좋은 선택입니다."
```

확인 항목:
- 파이프라인이 끝까지 완주하는가 (에러 없이 판정 산출)
- 판정에 근거 조문 추적이 붙어 있는가
- 변경 전 대비 판정 구조가 회귀하지 않았는가 (이전 runs/ 기록과 비교 가능)

env 부재 시 실행하지 말고 필요한 변수 목록과 함께 **미검증**으로 보고한다.
이 프로젝트는 자격증명 부재 시 실패하는 것이 정상 계약이다.

## 4. 프로젝트 계약 검사

- 새 코드에 조용한 결정론 fallback이 없는가 (LLM/Neo4j 부재 시 명시적 실패)
- 새 API/함수에 workspace_id가 전파되는가
- 도메인 라벨·색이 컴포넌트에 하드코딩되지 않고 labels.ts를 쓰는가
- Cypher에 `id(...)` 대신 `elementId(...)`를 쓰는가
- print 대신 logging, 자격증명 하드코딩 없음

## 리포트 형식

오케스트레이션 모드(`_workspace/` 존재, 팀 협업 중)에서는 `_workspace/{NN}_qa_report.md`
파일로 기록하고, 단독 호출·상위 지침이 인라인 반환을 요구할 때는 파일 없이 같은 형식을
최종 메시지로 반환한다. 3분류:

```markdown
## 통과
- [항목] 근거

## 실패
- [항목] 파일:라인 · 기대 vs 실제 · 재현 방법 · 제안 수정

## 미검증
- [항목] 사유 (필요 env/환경)
```

실패 항목은 담당 에이전트에게 수정 요청을 보내고, 수정 후 **해당 항목만** 재검증한다.
