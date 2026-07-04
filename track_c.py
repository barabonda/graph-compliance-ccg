"""Track C(표현·브랜드세이프티) 실판정 오케스트레이션.

역할 분리(불변 계약 준수):
- **후보 검색(룰/임베딩)**: 광고 문장 ↔ RiskPattern 임베딩 유사도 + 축별 키워드 게이트로
  "어떤 축을 LLM 에게 물어볼지"만 결정한다(적용범위 게이팅).
- **판정(LLM)**: 후보 축에 대해서만 맥락을 해석해 실제 위반 여부·심각도를 판단하고,
  근거 CasePrecedent 를 인용한다.

불변 계약:
- 근거(CasePrecedent) 없는 축은 판정을 생성하지 않는다.
- 후보가 하나도 없으면 판정 없이 active 요약(judgments=[])을 반환한다(정상 — 위험 미검출).
- 게이트(CCG_ENABLE_TRACK_C)가 꺼져 있으면 정적 extension 요약을 반환(무회귀).
- 게이트가 켜졌는데 코퍼스가 없으면 **조용한 스킵이 아니라 명시적 RuntimeError**
  (결정론 fallback 금지 계약).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from llm_gateway import LLMGateway
from retriever import cosine
from risk_context import track_c_active_summary, track_c_extension_summary
from schemas import ReviewInput
from utils import uses_korean_law_context

LOGGER = logging.getLogger(__name__)

# 후보 게이트: 광고 문장이 어느 축의 RiskPattern 과 이 이상 유사하면 LLM 판정 후보로 승격.
# 임계값은 후보를 넓히는 쪽(저비용 게이트)이며, 실제 판정은 LLM 이 한다.
# v1 시드(짧은 큐레이션 문구 + 노이즈 많은 혐오 예문)에서는 임베딩 유사도가 낮게 나오므로
# 키워드 게이트가 명시적 표현의 주 신호이고, 임베딩은 키워드 없는 근접 패러프레이즈를 잡는
# 보조 신호(OR)다. 임계값은 CCG_TRACK_C_SIM_THRESHOLD 로 조정 가능.
PATTERN_SIMILARITY_THRESHOLD = float(os.environ.get("CCG_TRACK_C_SIM_THRESHOLD", "0.35"))
MAX_FLAGGED_SENTENCES = 6
PRECEDENT_CITATION_LIMIT = 8

NON_KR_OUTPUT_OVERRIDE = (
    "\nOUTPUT LANGUAGE OVERRIDE: this workspace is a non-Korean jurisdiction. Write ALL free-text "
    "output (why, flagged rationale) in ENGLISH."
)

TRACK_C_JUDGMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "axis_applies": {"type": "boolean"},
        "severity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
        "risk_score": {"type": "number"},
        "why": {"type": "string"},
        "cited_precedent_ids": {"type": "array", "items": {"type": "string"}},
        "flagged_spans": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["axis_applies", "severity", "risk_score", "why", "cited_precedent_ids", "flagged_spans"],
}


def track_c_enabled() -> bool:
    """CCG_ENABLE_TRACK_C 게이트(기본 false). 켜짐 토큰만 활성."""
    raw = os.environ.get("CCG_ENABLE_TRACK_C", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _gather_candidates(
    *,
    sentences: list[str],
    sentence_embeddings: list[list[float]],
    patterns: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """축별 후보: 임베딩 유사도(>=임계) OR 키워드 게이트 히트."""
    candidates: dict[str, dict[str, Any]] = {}

    def _bucket(axis_id: str, axis_label: str) -> dict[str, Any]:
        return candidates.setdefault(
            axis_id,
            {
                "axis_id": axis_id,
                "axis_label": axis_label,
                "best_similarity": 0.0,
                "matched_keywords": set(),
                "flagged_sentences": [],
            },
        )

    # 축별 키워드(패턴 행에 중복 실려오므로 축 단위로 1회만 취합).
    keywords_by_axis: dict[str, list[str]] = {}
    label_by_axis: dict[str, str] = {}
    for pat in patterns:
        keywords_by_axis.setdefault(pat["axis_id"], pat.get("keywords") or [])
        label_by_axis.setdefault(pat["axis_id"], pat.get("axis_label") or pat["axis_id"])

    for idx, (sentence, embedding) in enumerate(zip(sentences, sentence_embeddings)):
        # 임베딩 게이트
        best_by_axis: dict[str, float] = {}
        for pat in patterns:
            score = cosine(embedding, [float(v) for v in pat["embedding"]])
            if score > best_by_axis.get(pat["axis_id"], 0.0):
                best_by_axis[pat["axis_id"]] = score
        for axis_id, score in best_by_axis.items():
            if score >= PATTERN_SIMILARITY_THRESHOLD:
                bucket = _bucket(axis_id, label_by_axis[axis_id])
                bucket["best_similarity"] = max(bucket["best_similarity"], score)
                if sentence not in bucket["flagged_sentences"]:
                    bucket["flagged_sentences"].append(sentence)
        # 키워드 게이트
        for axis_id, keywords in keywords_by_axis.items():
            hits = [kw for kw in keywords if kw and kw in sentence]
            if hits:
                bucket = _bucket(axis_id, label_by_axis[axis_id])
                bucket["matched_keywords"].update(hits)
                if sentence not in bucket["flagged_sentences"]:
                    bucket["flagged_sentences"].append(sentence)

    for bucket in candidates.values():
        bucket["matched_keywords"] = sorted(bucket["matched_keywords"])
        bucket["flagged_sentences"] = bucket["flagged_sentences"][:MAX_FLAGGED_SENTENCES]
    return candidates


def _judge_axis(
    *,
    llm: LLMGateway,
    review_input: ReviewInput,
    candidate: dict[str, Any],
    precedents: list[dict[str, Any]],
    mitigation: str,
) -> dict[str, Any] | None:
    """후보 축 1개를 LLM 이 맥락 판정. axis_applies=false 면 None(판정 미생성)."""
    precedent_lines = "\n".join(
        f"- [{p['id']}] ({p.get('source_label', '')}/{p.get('source_dataset', '')}) {p['text']}"
        for p in precedents
    )
    flagged = "\n".join(f"- {s}" for s in candidate["flagged_sentences"]) or "(직접 히트 문장 없음)"
    result = llm.structured(
        name="graphcompliance_track_c_axis",
        schema=TRACK_C_JUDGMENT_SCHEMA,
        system=(
            "당신은 한국 금융광고의 표현·브랜드세이프티 리스크(Track C)를 판단합니다. "
            "주어진 하나의 리스크 축에 대해, 광고 문안이 그 축의 혐오·차별·브랜드 훼손 표현에 "
            "해당하는지 맥락으로 해석하세요. 후보는 임베딩/키워드로 이미 좁혀졌으니, 당신의 역할은 "
            "표면 매칭이 아니라 '실제로 그 축의 문제 표현인가'를 판단하는 것입니다. "
            "반드시 제시된 CasePrecedent(선례 예문) 중 실제로 근거가 되는 것만 cited_precedent_ids 에 "
            "인용하세요. 근거로 삼을 선례가 없다면 axis_applies=false 로 두세요. "
            "flagged_spans 에는 문제되는 광고 문장을 그대로 담고, why 에는 어떤 선례와 어떻게 닮았는지 "
            "구체적으로 적으세요. 법적 위반을 단정하지 말고 라우팅용 리스크만 판단합니다. 모든 산출은 한국어."
            + ("" if uses_korean_law_context(review_input.workspace_id) else NON_KR_OUTPUT_OVERRIDE)
        ),
        user=(
            f"[리스크 축]\n{candidate['axis_label']} (id={candidate['axis_id']})\n\n"
            f"[후보 신호]\n키워드 히트: {candidate['matched_keywords']}\n"
            f"최대 패턴 유사도: {candidate['best_similarity']:.3f}\n\n"
            f"[광고 문안]\ntitle={review_input.title}\n{review_input.content_text}\n\n"
            f"[히트 문장]\n{flagged}\n\n"
            f"[선례(CasePrecedent) — 근거 후보]\n{precedent_lines}\n\n"
            f"[완화 가이드]\n{mitigation}"
        ),
    )
    if not result.get("axis_applies"):
        return None
    valid_ids = {p["id"] for p in precedents}
    cited = [pid for pid in result.get("cited_precedent_ids", []) if pid in valid_ids]
    if not cited:
        # 근거 없는 판정 금지: LLM 이 축이 적용된다 했으나 유효한 선례를 인용하지 못하면
        # 판정을 생성하지 않는다(계약).
        LOGGER.info("track_c.axis_dropped axis=%s reason=no_valid_precedent_citation", candidate["axis_id"])
        return None
    return {
        "axis_id": candidate["axis_id"],
        "axis_label": candidate["axis_label"],
        "severity": result["severity"],
        "risk_score": max(0.0, min(1.0, float(result["risk_score"]))),
        "why": result["why"],
        "flagged_spans": result.get("flagged_spans", []) or candidate["flagged_sentences"],
        "cited_precedents": [p for p in precedents if p["id"] in set(cited)],
        "mitigation": mitigation,
        "candidate_signal": {
            "best_similarity": candidate["best_similarity"],
            "matched_keywords": candidate["matched_keywords"],
        },
    }


def run_track_c(
    *,
    review_input: ReviewInput,
    sentences: list[str],
    retriever: Any,
    llm: LLMGateway,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Track C 요약을 반환. 게이트 OFF 면 정적 extension 요약(무회귀).

    게이트 ON:
    - 코퍼스 미적재 → RuntimeError(명시적 실패, fallback 금지).
    - 후보 없음 → active 요약 + judgments=[].
    - 후보 있음 → 근거 있는 축만 LLM 판정.
    """
    if enabled is None:
        enabled = track_c_enabled()
    if not enabled:
        return track_c_extension_summary()

    workspace_id = review_input.workspace_id
    ready = retriever.track_c_data_ready(workspace_id=workspace_id)
    if ready["axes"] == 0 or ready["patterns"] == 0 or ready["cases"] == 0:
        raise RuntimeError(
            "CCG_ENABLE_TRACK_C 가 켜졌지만 Track C 코퍼스가 로컬 DB 에 없습니다 "
            f"(RiskAxis={ready['axes']}, 임베딩 RiskPattern={ready['patterns']}, "
            f"CasePrecedent={ready['cases']}). load_risk_corpus.py 로 적재한 뒤 다시 시도하세요. "
            "(결정론 fallback 금지: 데이터 없이 조용히 스킵하지 않습니다.)"
        )

    clean_sentences = [s for s in (sentences or []) if s and s.strip()]
    if not clean_sentences:
        return track_c_active_summary(
            judgments=[],
            candidate_diagnostics={"candidate_axes": [], "skipped_no_precedent": [], "corpus": ready},
        )

    patterns = retriever.track_c_patterns(workspace_id=workspace_id)
    sentence_embeddings = retriever.embedder.embed_many(clean_sentences)
    candidates = _gather_candidates(
        sentences=clean_sentences,
        sentence_embeddings=sentence_embeddings,
        patterns=patterns,
    )

    judgments: list[dict[str, Any]] = []
    skipped_no_precedent: list[str] = []
    candidate_axes_diag: list[dict[str, Any]] = []
    for axis_id, candidate in sorted(candidates.items(), key=lambda kv: kv[1]["best_similarity"], reverse=True):
        precedents = retriever.track_c_precedents(
            workspace_id=workspace_id, axis_id=axis_id, limit=PRECEDENT_CITATION_LIMIT
        )
        candidate_axes_diag.append({
            "axis_id": axis_id,
            "axis_label": candidate["axis_label"],
            "best_similarity": candidate["best_similarity"],
            "matched_keywords": candidate["matched_keywords"],
            "precedent_count": len(precedents),
        })
        if not precedents:
            # 근거 없는 축: 판정 생성 금지, 조용히 버리지 않고 진단에 남긴다.
            skipped_no_precedent.append(axis_id)
            continue
        mitigation = retriever.track_c_mitigation(workspace_id=workspace_id, axis_id=axis_id)
        judgment = _judge_axis(
            llm=llm,
            review_input=review_input,
            candidate=candidate,
            precedents=precedents,
            mitigation=mitigation,
        )
        if judgment is not None:
            judgments.append(judgment)

    LOGGER.info(
        "track_c.completed ws=%s candidates=%d judgments=%d skipped_no_precedent=%d",
        workspace_id, len(candidates), len(judgments), len(skipped_no_precedent),
    )
    return track_c_active_summary(
        judgments=judgments,
        candidate_diagnostics={
            "candidate_axes": candidate_axes_diag,
            "skipped_no_precedent": skipped_no_precedent,
            "corpus": ready,
        },
    )
