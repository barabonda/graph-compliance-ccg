# JB Compliance 발표 자료 제작 가이드

이 폴더는 JB금융그룹 Fin.AI Challenge의 AI Agent 서비스 평가를 위한 발표 자료 제작용 작업 공간이다. 목표는 심사위원이 짧은 시간 안에 "무엇을 만들었고, 왜 금융업무에 필요하며, 실제로 구현 가능한가"를 이해하도록 돕는 것이다.

## 작업 원칙

- 아직 PPT 파일은 만들지 않는다. 사용자가 승인한 뒤에만 `output/` 아래에 산출물을 만든다.
- 발표 자료는 쉬운 말로 작성한다. 내부 구현 용어는 필요할 때만 쓰고, 먼저 업무 가치로 설명한다.
- "AI가 최종 법률 판단을 대체한다"가 아니라 "준법 담당자의 1차 검토, 근거 확인, 수정 제안을 돕는다"로 포지셔닝한다.
- 모든 주장은 근거를 붙인다. 근거는 기능명세서, MVP 제안서, 실제 콘솔 화면, 소스 코드, 평가 결과 중 하나로 연결한다.
- 환각 방지를 강조한다. 상품 사실, 필수 고지, 적용 범위는 그래프와 구조화 데이터로 먼저 좁히고 LLM은 해석이 필요한 부분만 맡는다고 설명한다.
- Track A, Track B라는 이름은 내부 구조로만 쓰고, 발표에서는 "개별 조항 심사"와 "전체 인상 심사"라는 표현을 우선한다.

## 참고 우선순위

1. `context/deck-brief.md`: 발표 전체 흐름과 슬라이드별 메시지
2. `context/evaluation.md`: 심사 기준별 대응 논리
3. `brand/DESIGN.md`: 화면 톤, 색상, 도식 규칙
4. `../README.md`: 현재 CCG 앱의 기능과 실행 구조
5. `../docs/REASONING_ARCHITECTURE.md`: 규칙/그래프/LLM 추론 구조
6. `../docs/JB금융 Fin AI Challenge 기능명세서 - JunBub (3).docx`
7. `../docs/[데이콘] JB금융그룹 Fin AI Challenge MVP제안서_제출본_JunBub 팀.pdf`

## 발표 핵심 메시지

서비스명 후보는 `JunBub` 또는 `JB Compliance · Content Safeguard`를 기본으로 둔다.

한 줄 소개:

> 금융광고 초안을 상품설명서 사실, 금소법/심의기준, 필수 고지와 대조해 위반 가능성·누락 고지·수정안을 근거와 함께 제시하는 준법 사전심사 AI Agent.

차별화 문장:

> 단순 RAG 챗봇이 아니라, 광고 문구를 Claim 단위로 쪼개고 Policy Graph, Product Fact Graph, Disclosure Gate로 판단 범위를 좁힌 뒤 LLM이 필요한 해석만 수행하는 Graph-gated Compliance Agent다.

## 제작할 슬라이드의 기본 구조

1. Summary: 서비스명, 지정주제, 한 줄 소개
2. Problem Definition: 금융광고 심사의 병목과 리스크
3. Solution Overview: Policy Graph + Context Graph + Product Fact Graph + LLM Judge
4. Key Features: 문구별 리스크, 상품 사실 대조, 필수 고지, 수정안, 감사추적
5. Data & Tech: 데이터, Neo4j, LLM, rerank, 평가 지표
6. User Scenario: 마케터와 준법 담당자의 사용 흐름
7. Expected Impact: 업무효율, 리스크 감소, 확장성

## 금지 사항

- 확정적인 법률 자문처럼 표현하지 않는다.
- "완전 자동 승인"처럼 들리는 표현을 쓰지 않는다.
- 내부 ID, raw score, 모델 로그를 메인 장표에 노출하지 않는다.
- 긴 법령 원문을 장표 본문에 그대로 붙이지 않는다.
- 기능이 구현되지 않았거나 검증되지 않은 내용을 현재 완료 기능처럼 표현하지 않는다.

## 산출물 규칙

- 원본 자료와 캡처 이미지는 `assets/`에 둔다.
- 생성된 PPT, PDF, 이미지 export는 `output/`에 둔다.
- 슬라이드 문구는 심사위원용으로 짧게 쓴다. 상세한 기술 설명은 발표자 노트 또는 보조 장표로 분리한다.
- 파일명에는 날짜와 버전을 포함한다. 예: `junbub_mvp_pitch_20260704_v1.pptx`

