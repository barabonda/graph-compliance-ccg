---
name: ccg-backend
description: "graph-compliance-ccg 백엔드 작업 가이드. FastAPI 서버(server.py), 심사 파이프라인(workflow.py), 그래프 검색(retriever.py), 판정(judge.py), LLM 게이트웨이(llm_gateway.py), 실행 기록(run_store.py) 수정·확장 시 반드시 이 스킬을 사용. 심사 API 추가, 파이프라인 단계 변경, Claude/로컬 모델 라우팅, Neo4j 쿼리, workspace_id 관련 작업 포함."
---

# CCG Backend 작업 가이드

## 모듈 지도

| 영역 | 파일 | 비고 |
|------|------|------|
| API 서버 | `server.py` (포트 8770) | 엔드포인트 목록은 아래 |
| 심사 파이프라인 | `workflow.py` | 룰→그래프검색→LLM판정 오케스트레이션 |
| 그래프 검색 | `retriever.py`, `router.py` | PolicyHypernym/CU 후보 검색, CU 게이팅 |
| 판정 | `judge.py`, `rule_judgment.py`, `overall_impression.py` | 개별 + 종합(Track B) |
| LLM 게이트웨이 | `llm_gateway.py` | OpenAI/Claude/로컬 Ollama 라우팅 |
| 실행 기록 | `run_store.py`, `persistence.py` | 대시보드가 소비 |
| 수정안 | `revision.py` | 원문↔교정본 diff |
| 상품 사실 | `product_facts.py`, `disclosure_catalog.py` | 필수고지 `disc_*` 카탈로그 |
| 코파일럿 | `copilot_agent.py`, `copilot_graph_tools.py`, `copilot_tools.py` | KR 그래프 읽기는 팀 Aura로 라우팅 |

주요 엔드포인트: `POST /api/review`, `POST /api/review/stream`,
`GET /api/runs`, `GET /api/runs/{run_id}`, `POST /api/copilot`,
`GET /api/products/search`, `GET /api/product-doc/{document_id}`,
`POST /copilot-agent`, `GET /health`.

## 불변 계약 (위반 금지)

1. **결정론 fallback 금지** — LLM 키/Neo4j 부재 시 규칙 기반으로 조용히 대체하지 않고
   명시적 에러를 낸다. 이유: 심사 결과의 신뢰성 계약. 부재를 숨기면 저품질 판정이
   정상처럼 유통된다.
2. **workspace_id 전파** — KR `graphcompliance_mvp_jb_20260530`,
   KH `graphcompliance_cambodia_ppcbank_20260630`. 2-DB 아키텍처: KR 그래프 읽기는
   팀 Aura 인스턴스로 라우팅된다. 새 함수/엔드포인트에 workspace_id 파라미터를 유지하라.
3. **룰/LLM 역할 분리** — 적용범위 게이팅·필수고지 누락·기계적 위반은 룰(그래프
   카탈로그)이 판정하고, LLM은 단정·오인 등 맥락 판단과 전체 인상 종합만 한다.
   LLM 프롬프트에 룰이 할 일을 밀어넣지 마라.
4. **Claude 계열 호환** — Claude 5 계열 호출 시 temperature 제거, thinking 명시적 off
   (`llm_gateway.py`의 기존 처리 참조). 구조화 출력은 로컬 경로에서
   `response_format=json_schema`를 쓴다.

## 작업 절차

1. 변경 대상 모듈과 그 소비자(프론트/다른 모듈)를 함께 파악한다.
   API 응답 shape을 바꾸면 `frontend/src/lib/types.ts` 소비자가 있다 —
   `_workspace/contract_api.md`에 새 shape을 기록하고 프론트 담당에게 알린다.
2. 구현: 타입 힌트, logging(print 금지), 자격증명은 env로(`env_loader.py`).
   Cypher는 `elementId(...)` 사용(`id(...)` 금지), 동적 라벨은 검증 후 보간.
3. 테스트: 변경 동작에 대한 테스트를 `tests/`(test_workflow.py, test_product_facts.py,
   test_revision.py)에 추가·수정.

## 실행 명령

프로젝트 루트: `/Users/barabonda/Documents/GraphRAG/examples/graph-compliance-ccg`

```bash
# 단위 테스트
python3 -m pytest tests/ -x -q

# 서버 기동 (env: OPENAI_API_KEY, ANTHROPIC_API_KEY, NEO4J_URI/USER/PASSWORD)
uvicorn server:app --port 8770

# 심사 스모크 (E2E)
python3 review_ad.py --text "지난 3년간 조기상환 성공률이 높았던 ELS, 중위험 투자자에게 좋은 선택입니다."
```

env가 없으면 스모크는 실패한다 — 이는 정상 동작(계약 1)이다. 필요한 env를 보고하고
"미검증"으로 처리하라.
