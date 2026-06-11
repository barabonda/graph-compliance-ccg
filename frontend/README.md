# GraphCompliance CCG Frontend

Next.js (App Router) + React + Tailwind 기반 금융광고 준법심사 콘솔.
`console/`의 vanilla JS 콘솔을 production-level 구조로 개편한 버전입니다.

## Run

백엔드(FastAPI)를 먼저 띄웁니다:

```bash
PYTHONPATH=examples/graph-compliance-ccg \
uvicorn server:app --app-dir examples/graph-compliance-ccg --port 8770
```

그다음 프론트엔드:

```bash
cd examples/graph-compliance-ccg/frontend
npm install
npm run dev          # http://localhost:3000
```

`/api/*`와 `/health`는 `next.config.ts`의 rewrites로 FastAPI(기본
`http://localhost:8770`)에 프록시됩니다. 백엔드 주소가 다르면:

```bash
CCG_API_BASE=http://other-host:8770 npm run dev
```

## Architecture

```text
src/
  app/page.tsx          단일 콘솔 페이지 (form → stream → result)
  hooks/useReview.ts    리뷰 상태 reducer + NDJSON 스트림 소비
  lib/types.ts          server.py ReviewOutput 계약의 TypeScript 미러
  lib/api.ts            /api/review/stream NDJSON 클라이언트 + 에러 매핑
  lib/labels.ts         한국어 라벨/6대 판매원칙/예시 프리셋
  lib/selectors.ts      ReviewOutput 위의 순수 read-model 헬퍼
                        (하이라이트 span 계산, 원칙별 집계, anchor 선택 등)
  components/           VerdictHeader · RiskStrip · HighlightedText ·
                        DetailPanel · tabs/(Overall, SentenceMap, ClaimCards,
                        EvidencePath, ProductFacts, Audit)
  fixtures/             실제 백엔드 응답 스냅샷 (샘플 결과 보기 버튼,
                        백엔드 없이 UI 개발할 때 사용)
```

설계 원칙:

- `lib/selectors.ts`는 전부 순수 함수 — 레거시 콘솔(`console/app.js`)의 판단
  표시 시맨틱을 그대로 포팅했으며, 컴포넌트는 표시만 담당합니다.
- 리뷰 실행은 `POST /api/review/stream`(NDJSON)을 사용해 단계별 이벤트를
  감사 추적 탭에 실시간 표시하고, `result` 이벤트로 화면을 채웁니다.
- 에러는 FastAPI의 `{error, message, cause}` detail 계약을 그대로 표면화합니다.

## Quality gates

```bash
npm run lint
npx tsc --noEmit
npm run build
```
