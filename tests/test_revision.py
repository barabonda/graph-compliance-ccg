"""교정본(integrated_revision) 데이터 플로우 결함 회귀 테스트.

배경 결함:
- per-span `after`는 조언을 걸렀지만, 전체 교정본은 `!= 원문` 외 검증이 없어
  조언·조각·미수정 no-op이 '수정 문건' 자리에 들어갔다(실측: 줄바꿈만 다른 본).
- 재작성 LLM이 risky span만 받아 누락 고지·전체 인상을 못 고쳤고, per-span 위반이
  없으면 교정본을 아예 안 만들었다.

이 테스트는 (1) 순수 검증 함수의 거부/통과, (2) suggest()의 컨텍스트 기반 생성과
검증 결합을 가짜 LLM으로 고정한다.
"""

from __future__ import annotations

from revision import (
    DISCLOSURE_BLOCK_ANCHOR,
    DOCUMENT_REVISION_ANCHOR,
    LLMRevisionSuggester,
    build_disclosure_block,
    render_disclosure_block,
    revision_context,
    validate_integrated_revision,
)
from schemas import ReviewGraph, ReviewInput


def _check(check_id, label, *, present, gate="ON"):
    return {"check_id": check_id, "label": label, "present": present, "gate_status": gate}


def _graph(*, checks=None, track_b=None):
    return ReviewGraph(
        review_run_id="r",
        ad_draft_id="a",
        content_hash="h",
        product_fact_context={"disclosure_checks": checks or [], "comparison_results": []},
        overall_impression_judgment=({"verdict": track_b} if track_b else {}),
    )


ORIGINAL = "JB 특판예금 출시. 누구나 연 5% 확정 보장 수익을 받을 수 있는 절호의 기회입니다. 지금 가입하면 조건 없이 안정적인 고수익을 보장합니다."


# ── 순수 검증 함수 ───────────────────────────────────────────────────────────

def test_rejects_whitespace_only_diff_noop():
    # 실측 버그: 줄바꿈 하나만 추가된 미수정본이 교정본으로 통과했다.
    noop = ORIGINAL.replace("기회입니다. ", "기회입니다.\n")
    assert noop != ORIGINAL  # 글자상 다름(기존 가드는 여기서 통과시켰음)
    assert validate_integrated_revision(noop, ORIGINAL) is None


def test_rejects_reviewer_advice_as_document():
    advice = "예금자보호 문구를 추가하고 우대조건을 함께 표시하세요."
    assert validate_integrated_revision(advice, ORIGINAL) is None


def test_rejects_suggestion_list_as_document():
    listish = "- 누구나 → 가입대상 명시\n- 확정 보장 → 변동 가능 표기\n- 조건 없이 → 삭제"
    assert validate_integrated_revision(listish, ORIGINAL) is None


def test_rejects_fragment_too_short():
    fragment = "연 5% 금리."
    assert validate_integrated_revision(fragment, ORIGINAL) is None


def test_rejects_empty_or_identical():
    assert validate_integrated_revision("", ORIGINAL) is None
    assert validate_integrated_revision(ORIGINAL, ORIGINAL) is None


def test_accepts_genuine_full_rewrite_with_cta():
    # CTA('가입하세요')가 있어도 진짜 광고 교정본은 통과해야 한다.
    good = (
        "JB 특판예금 출시. 연 5% 금리는 가입기간·우대조건 충족 시 적용되며 변동될 수 있습니다. "
        "예금자보호법에 따라 1인당 최고 1억원까지 보호됩니다. 자세한 내용은 상품설명서를 확인하고 지금 가입하세요."
    )
    assert validate_integrated_revision(good, ORIGINAL) == good


# ── 게이트 인지: 적용범위 밖(OFF) 고지를 누락으로 오인하면 안 됨 ──────────────

def test_revision_context_ignores_gate_off_disclosures():
    # 실측 버그: 예금 광고에 대출·투자 고지(OFF)가 '누락'으로 들어왔다.
    graph = _graph(checks=[
        _check("disc_depositor_protection_notice", "예금자보호 여부 및 한도", present=False, gate="ON"),
        _check("disc_principal_loss_notice", "원금손실 가능성 고지", present=False, gate="OFF"),  # 투자 고지
        _check("disc_overdue_interest_rate", "연체이자율 고지", present=False, gate="OFF"),       # 대출 고지
        _check("disc_seller_name", "판매업자 명칭", present=True, gate="ON"),
    ])
    labels = [d["label"] for d in revision_context(graph)["missing_disclosures"]]
    assert labels == ["예금자보호 여부 및 한도"]  # OFF 두 개는 제외


def test_build_disclosure_block_only_applicable_missing():
    graph = _graph(checks=[
        _check("disc_depositor_protection_notice", "예금자보호 여부 및 한도", present=False, gate="ON"),
        _check("disc_variable_rate_notice", "금리·수익률 변동 가능성", present=True, gate="ON"),   # 이미 있음
        _check("disc_principal_loss_notice", "원금손실 가능성 고지", present=False, gate="OFF"),    # 적용범위 밖
    ])
    block = build_disclosure_block(graph)
    cids = {b["check_id"] for b in block}
    assert cids == {"disc_depositor_protection_notice"}  # present·OFF 제외
    assert block[0]["status"] == "add" and "예금자보호법" in block[0]["text"]


def test_build_disclosure_block_marks_reviewer_only_for_non_templated():
    graph = _graph(checks=[
        _check("disc_review_approval_notice", "준법감시인 심의필", present=False, gate="ON"),  # 번호 필요 → 심사자
    ])
    block = build_disclosure_block(graph)
    assert block[0]["status"] == "reviewer" and block[0]["text"] == ""


def test_render_disclosure_block_bottom_bullet_format():
    block = build_disclosure_block(_graph(checks=[
        _check("disc_depositor_protection_notice", "예금자보호 여부 및 한도", present=False, gate="ON"),
        _check("disc_variable_rate_notice", "금리·수익률 변동 가능성", present=False, gate="ON"),
    ]))
    text = render_disclosure_block(block)
    lines = text.splitlines()
    assert lines[0] == "꼭 확인해 주세요!"
    assert all(ln.startswith("ㆍ") for ln in lines[1:])
    assert len(lines) == 3


def test_fully_compliant_real_ad_shape_needs_no_block():
    # 실제 광고처럼 ON 고지가 모두 present, OFF는 부재 → 추가할 고지 0개.
    block = build_disclosure_block(_graph(checks=[
        _check("disc_depositor_protection_notice", "예금자보호", present=True, gate="ON"),
        _check("disc_variable_rate_notice", "변동 가능성", present=True, gate="ON"),
        _check("disc_principal_loss_notice", "원금손실", present=False, gate="OFF"),
        _check("disc_overdue_interest_rate", "연체이자율", present=False, gate="OFF"),
    ]))
    assert block == []
    assert render_disclosure_block(block) == ""


# ── suggest(): 하단 고지 블록 첨부, inline 교정본 폐기 ────────────────────────

class _FakeGateway:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def structured(self, **_kwargs):
        self.calls += 1
        return self.payload


def test_suggest_skips_llm_when_nothing_actionable():
    # ON 고지 모두 present, OFF만 부재, Track B 없음 → 할 일 없음.
    gw = _FakeGateway({"suggestions": [], "integrated_revision": "x"})
    graph = _graph(checks=[
        _check("disc_depositor_protection_notice", "예금자보호", present=True, gate="ON"),
        _check("disc_principal_loss_notice", "원금손실", present=False, gate="OFF"),
    ])
    out = LLMRevisionSuggester(gw).suggest(review_input=ReviewInput(content_text=ORIGINAL), graph=graph)
    assert out == []
    assert gw.calls == 0


def test_suggest_emits_disclosure_block_not_inline_document():
    # per-span 위반 없이 고지 누락(ON)만 있어도 하단 블록을 첨부. inline __document__는 절대 X.
    gw = _FakeGateway({"suggestions": [], "integrated_revision": "무시되는 전체재작성문"})
    graph = _graph(checks=[
        _check("disc_depositor_protection_notice", "예금자보호 여부 및 한도", present=False, gate="ON"),
        _check("disc_principal_loss_notice", "원금손실", present=False, gate="OFF"),  # 들어가면 안 됨
    ])
    out = LLMRevisionSuggester(gw).suggest(review_input=ReviewInput(content_text=ORIGINAL), graph=graph)
    assert gw.calls == 1
    assert [s for s in out if s["anchor_id"] == DOCUMENT_REVISION_ANCHOR] == []  # inline 교정본 폐기
    blocks = [s for s in out if s["anchor_id"] == DISCLOSURE_BLOCK_ANCHOR]
    assert len(blocks) == 1
    assert "예금자보호법" in blocks[0]["after"]
    assert "원금손실" not in blocks[0]["after"]  # OFF 고지는 절대 추가 안 함


def test_suggest_no_block_when_only_off_disclosures_missing():
    # Track B만 있고 ON 누락 고지가 없으면 고지 블록은 비어 첨부 안 함.
    gw = _FakeGateway({"suggestions": [], "integrated_revision": "x"})
    graph = _graph(
        checks=[_check("disc_overdue_interest_rate", "연체이자율", present=False, gate="OFF")],
        track_b="MEDIUM",
    )
    out = LLMRevisionSuggester(gw).suggest(review_input=ReviewInput(content_text=ORIGINAL), graph=graph)
    assert gw.calls == 1  # Track B로 needs_revision True → LLM 호출
    assert [s for s in out if s["anchor_id"] == DISCLOSURE_BLOCK_ANCHOR] == []
    assert [s for s in out if s["anchor_id"] == DOCUMENT_REVISION_ANCHOR] == []
