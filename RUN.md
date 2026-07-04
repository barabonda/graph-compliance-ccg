# RUN.md — JB Compliance · CONTENT SAFEGUARD 로컬 실행 가이드

> 팀 원본 `barabonda/graph-compliance-ccg` 을 `piso7/JB-Fin-compliance-ai` 로 미러링한 작업본.
> 작업 브랜치: `feature/kh-compliance`

## 리모트 구성
| 리모트 | URL | 용도 |
|---|---|---|
| `origin` | https://github.com/piso7/JB-Fin-compliance-ai | 내 작업 repo (**push 대상**) |
| `upstream` | https://github.com/barabonda/graph-compliance-ccg | 팀 원본 (**fetch 전용**, push는 `DISABLE`로 차단) |

- 작업 push는 origin 으로만: `git push origin feature/kh-compliance`
- 팀 변경 동기화(나중에): `git fetch upstream && git merge upstream/main`

## 사전 요구사항
- **Python >= 3.10** (`requirements.txt`의 fastapi 0.135 / pydantic 2.12 등이 3.10+ 요구).
  시스템 python3는 3.9.6이라 부족 → **uv로 Python 3.12.13을 받아 `../.venv`에 구성 완료**.
  (다른 환경에서 재현 시: `curl -LsSf https://astral.sh/uv/install.sh | sh && uv python install 3.12`)
- **Node >= 18** — 현재 v22.22.2 OK
- 외부 자원: **OpenAI API 키**, **Neo4j 인스턴스**(URI/USER/PASSWORD)
  - README상 LLM 자격증명/Neo4j 없으면 규칙으로 조용히 대체하지 않고 **실패**한다.

## 디렉터리 레이아웃
- 백엔드 (Python · FastAPI): **저장소 루트** (`server.py`, `workflow.py`, …)
- 프론트엔드 (Next.js 16 콘솔): `frontend/`

## 환경변수 (값은 비어 있음 — 직접 채울 것)
- 루트 `.env` : `OPENAI_API_KEY`, `OPENAI_MODEL`, `NEO4J_URI/USER/PASSWORD/DATABASE`, (선택) 로컬 LLM 토글 등
- `frontend/.env.local` : `LLM_BASE_URL`, `LLM_API_KEY`
- 두 파일 모두 `.gitignore`로 커밋 제외됨. **절대 커밋 금지.** (기본값 참고는 각 `.env.example`)

## 백엔드 실행
venv는 이미 `../.venv`(= junbub/.venv, Python 3.12.13)에 생성·설치 완료. 활성화 후 실행:
```bash
cd <repo>                       # = .../junbub/repo
source ../.venv/bin/activate    # venv: junbub/.venv (Python 3.12.13, uv로 생성)
# 재생성이 필요하면: uv venv --python 3.12 ../.venv && uv pip install -r requirements.txt
# .env 값을 채운 뒤:
uvicorn server:app --port 8770  # 반드시 repo 루트에서 실행 (.env를 CWD에서 읽음)
```
- 헬스 체크: `curl http://localhost:8770/health`
- 레거시 바닐라 콘솔: http://localhost:8770/console
- 단발 리뷰 CLI 예시: `python3 review_ad.py --text "..."` (OpenAI 키 + Neo4j 필요)

## 프론트엔드 실행
```bash
cd <repo>/frontend
npm install
npm run dev                     # http://localhost:3000  (/api/*, /health → 백엔드 :8770 프록시)
```

## 베이스라인 상태 (2026-06-30 확인)
- **프론트엔드: ✓ 정상** — dev 서버 HTTP 200 부팅, `✓ Ready`, `.env.local` 로드 확인.
- **백엔드: ✓ 정상** — uv로 Python 3.12.13 구성, 33개 의존성 설치 완료.
  `uvicorn server:app --port 8770` 부팅 후 `GET /health` → `200 {"status":"ok"}`, `/console` → 307 확인.
  (전체 심사 동작은 OpenAI 키 + Neo4j 필요.)

## 보안 메모
- 클론된 git 히스토리(61 커밋) 비밀정보 스캔: **실제 자격증명 없음** (로테이션 불필요).
- 단, `.env.example`들에 내부 인프라 엔드포인트(Tailscale `mac-mini-m4-llm.tail023e97.ts.net`,
  IP `100.103.82.56`)가 노출돼 있음 — 자격증명은 아니나 내부망 정보. 공개 repo 전환 시 유의.
