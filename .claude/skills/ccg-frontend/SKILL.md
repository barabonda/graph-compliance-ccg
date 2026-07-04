---
name: ccg-frontend
description: "graph-compliance-ccg 심사 콘솔(Next.js frontend/) 작업 가이드. 3-pane 콘솔, 위험 카드, 판정 상세, 코파일럿 패널, 수정안 diff, 운영 대시보드, 은행/모델 선택 UI 수정·확장 시 반드시 이 스킬을 사용. 컴포넌트 추가, 라벨/색상 변경, API 연동, 타입 정의 작업 포함."
---

# CCG Frontend 작업 가이드

## 구조 지도

루트: `frontend/` (Next.js, `npm run dev` → http://localhost:3000, `/api/*`를
FastAPI 8770으로 프록시)

| 영역 | 경로 | 비고 |
|------|------|------|
| 페이지/프록시 | `src/app/` (`api/chat`, `api/copilotkit`, `api/review`) | 프록시 라우트 |
| 심사 콘솔 | `src/components/console/` | 3-pane: 원문 하이라이트·위험 카드·판정 상세 |
| 코파일럿 | `src/components/copilot/`, `CopilotPanel.tsx` | |
| 탭/셸 | `src/components/tabs/`, `src/components/shell/` | 수정안 diff 포함 |
| 입력 폼 | `ReviewForm.tsx`, `PipelineProgress.tsx` | |
| 상태 훅 | `src/hooks/useReview.ts` | 심사 실행·스트림 소비의 중심 |
| 라이브러리 | `src/lib/` — `api.ts`(fetch), `types.ts`(API 타입), `labels.ts`(도메인 라벨·색·BANKS), `selectors.ts`, `revisionDiff.ts`, `copilotContext.ts` | |

## 불변 계약 (위반 금지)

1. **API shape 추측 금지** — 백엔드 응답 타입은 `_workspace/contract_api.md` 또는
   `server.py`의 실제 반환 코드에서 확인하고 `lib/types.ts`에 반영한다.
   `as any`·제네릭 캐스팅으로 불일치를 덮으면 컴파일은 통과하지만 런타임에 깨진다.
2. **labels.ts 중앙화** — 심의 카테고리 색(설명의무=보라, 부당권유=빨강 등), 판정
   라벨, BANKS(전북·광주=KR workspace, PPCBank=KH workspace)는 `lib/labels.ts`에서만
   관리한다. 컴포넌트에 도메인 라벨·색을 하드코딩하지 마라 — 변형 표기 매칭 로직이
   labels.ts에 있다.
3. **workspace 라우팅 보존** — 은행 선택이 workspace_id를 결정하고 백엔드 정책 그래프
   라우팅으로 이어진다. 은행/관할 관련 UI 변경 시 BANKS 구조를 유지하라.
4. **심사 도메인 용어 창작 금지** — 금감원 회답식 구조(정의→요건→결론→유보), 판정
   5종 등 도메인 용어는 기존 labels.ts와 컴포넌트의 표기를 따른다.

## 작업 절차

1. 소비할 API의 실제 응답 shape 확인 (`contract_api.md` → 없으면 `server.py` 직접).
2. `lib/types.ts` 갱신 → `lib/api.ts`/훅 → 컴포넌트 순으로 구현.
3. 스타일·아이콘은 기존 관례(`ui.tsx`, `Icon.tsx`, globals.css) 재사용.
4. 검증: `cd frontend && npx tsc --noEmit`. 필요 시 `npm run build`.

## 실행 명령

```bash
cd frontend
npm run dev          # http://localhost:3000 (백엔드 8770 필요)
npx tsc --noEmit     # 타입 검증 (최소 완료 기준)
npm run build        # 전체 빌드 검증
```

백엔드 미기동 상태에선 화면 동작 확인이 제한된다 — 그 경우 tsc 통과까지 확인하고
"런타임 미검증(백엔드 필요)"으로 보고하라.
