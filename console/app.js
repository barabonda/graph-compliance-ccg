const PRINCIPLES = [
  { key: "suitability", label: "적합성", match: ["적합성"] },
  { key: "appropriateness", label: "적정성", match: ["적정성"] },
  { key: "explanation", label: "설명의무", match: ["설명", "고지"] },
  { key: "unfair_sales", label: "불공정영업", match: ["불공정"] },
  { key: "unfair_solicitation", label: "부당권유", match: ["부당권유", "단정"] },
  { key: "ad_regulation", label: "광고규제", match: ["광고", "허위", "과장", "오도", "보장"] },
];

const VERDICT_LABELS = {
  pass_candidate: ["통과 후보", "현재 문안 기준 중대한 위반 신호 없음"],
  needs_review: ["검토 필요", "근거 또는 정책 매칭 확인 필요"],
  revise: ["수정 필요", "일부 표현 또는 고지 보완 필요"],
  reject: ["반려", "명백한 위반 가능성이 있어 배포 전 수정 필요"],
};

const JUDGMENT_STATUS = {
  NON_COMPLIANT: "위반 가능성",
  RETRIEVAL_FAILURE: "정책 매칭 실패",
  INSUFFICIENT: "검토 필요",
  COMPLIANT: "문제 없음",
  NOT_APPLICABLE: "해당 없음",
  SCOPE: "범위 정보",
  ANCHOR: "검토됨",
};

const HUMAN_ACTION_LABELS = {
  guarantee_or_return_misleading: "단정·보장 표현",
  condition_or_scope_missing: "조건 고지",
  required_disclosure_missing: "필수 고지 누락",
  past_performance_or_future_return: "과거성과 오인",
  comparison_ad: "비교 표현",
  unfair_superior_position_sales: "불공정 영업",
};

const HUMAN_FEATURE_LABELS = {
  guarantee_expression: "보장 표현",
  certainty_expression: "확정 표현",
  unconditional_expression: "조건 없음",
  universal_scope_expression: "대상 범위",
  comparison_target: "비교 근거",
  coercion_or_tie_in_context: "강요·끼워팔기",
};

const QUALIFIER_LABELS = {
  target_scope: "대상 범위",
  condition_scope: "조건 범위",
  certainty: "확정 표현",
  guarantee: "보장 표현",
  benefit_scope: "혜택 범위",
  risk_downplay: "위험 축소",
  urgency: "긴급성",
  comparison: "비교 표현",
  disclosure_qualifier: "고지 표현",
  other: "표현",
};

const DISCLOSURE_LABELS = {
  deposit_rate_condition: "최고금리 조건",
  deposit_term: "가입기간",
  deposit_tax_basis: "세전/세후",
  depositor_protection_limit: "예금자보호",
  product_document_notice: "상품설명서",
};

const EXAMPLES = [
  {
    label: "예금 · 고지 있음",
    product: "deposit",
    channel: "web_page",
    title: "JB시니어우대예금 특판",
    selectedProduct: "JB시니어우대예금",
    text:
      "JB시니어우대예금 특판 안내. 최고 연 5.0% 금리를 확정 제공하며 안정적으로 목돈을 관리할 수 있습니다. 기본금리와 우대금리는 가입기간, 우대조건 충족 여부에 따라 달라질 수 있습니다. 이 예금은 예금자보호법에 따라 원금과 이자를 합하여 1인당 최고 1억원까지 보호됩니다.",
  },
  {
    label: "예금 · 보장 위험",
    product: "deposit",
    channel: "web_page",
    title: "고지 없는 특판예금",
    selectedProduct: "",
    text:
      "JB 특판예금 출시. 누구나 연 5% 확정 보장 수익을 받을 수 있는 절호의 기회입니다. 지금 가입하면 조건 없이 안정적인 고수익을 보장합니다.",
  },
  {
    label: "투자 · ELS",
    product: "investment",
    channel: "web_page",
    title: "ELS 광고 초안",
    selectedProduct: "",
    text:
      "요즘 같은 변동성 장세에서는 ELS를 이해하는 것이 중요합니다. OO증권의 더블찬스 ELS는 안정성과 수익성을 동시에 고려한 상품입니다. 지난 3년간 유사 구조 상품의 조기상환 성공률이 높았기 때문에, 중위험 투자자에게 좋은 선택이 될 수 있습니다.",
  },
];

const state = {
  result: null,
  selectedAnchorId: "",
  selectedPrinciple: "",
  streamEvents: [],
  isStreaming: false,
};

const els = {
  form: document.getElementById("reviewForm"),
  title: document.getElementById("titleInput"),
  product: document.getElementById("productInput"),
  channel: document.getElementById("channelInput"),
  selectedProduct: document.getElementById("selectedProductInput"),
  text: document.getElementById("textInput"),
  examples: document.getElementById("examples"),
  button: document.getElementById("reviewButton"),
  error: document.getElementById("errorMessage"),
  verdictHeader: document.getElementById("verdictHeader"),
  riskStrip: document.getElementById("riskStrip"),
  highlightedText: document.getElementById("highlightedText"),
  highlightSummary: document.getElementById("highlightSummary"),
  conditionalNotice: document.getElementById("conditionalNotice"),
  detail: document.getElementById("detailContent"),
  runLabel: document.getElementById("reviewRunLabel"),
  copyRun: document.getElementById("copyRunButton"),
  overallTab: document.getElementById("overallTab"),
  sentencesTab: document.getElementById("sentencesTab"),
  claimsTab: document.getElementById("claimsTab"),
  graphCanvas: document.getElementById("graphCanvas"),
  productFactsTab: document.getElementById("productFactsTab"),
  auditTrace: document.getElementById("auditTrace"),
};

function init() {
  renderExamples();
  renderEmpty();
  els.form.addEventListener("submit", runReview);
  els.copyRun.addEventListener("click", copyRunId);
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.tab));
  });
  fillExample(EXAMPLES[1]);
}

function renderExamples() {
  els.examples.innerHTML = "";
  EXAMPLES.forEach((example) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "example-button";
    button.textContent = example.label;
    button.addEventListener("click", () => fillExample(example));
    els.examples.appendChild(button);
  });
}

function fillExample(example) {
  els.title.value = example.title;
  els.product.value = example.product;
  els.channel.value = example.channel;
  els.selectedProduct.value = example.selectedProduct || "";
  els.text.value = example.text;
}

async function runReview(event) {
  event.preventDefault();
  els.error.hidden = true;
  els.button.disabled = true;
  els.button.textContent = "Reviewing...";
  state.result = null;
  state.selectedAnchorId = "";
  state.selectedPrinciple = "";
  state.streamEvents = [];
  state.isStreaming = true;
  activateTab("audit");
  renderStreamingAudit();
  const payload = {
    dataset_item_id: `console_${Date.now()}`,
    title: els.title.value,
    content_text: els.text.value,
    channel: els.channel.value,
    product_group: els.product.value,
    selected_product_name: els.selectedProduct.value.trim(),
    workspace_id: "graphcompliance_mvp_jb_20260530",
  };
  try {
    const response = await fetch("/api/review/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(await formatApiError(response));
    }
    await consumeReviewStream(response);
    if (!state.result) {
      throw new Error("review_stream_finished_without_result: 결과 이벤트가 수신되지 않았습니다.");
    }
    els.error.textContent = "";
    els.error.hidden = true;
    state.selectedAnchorId = defaultAnchorId(state.result);
    state.selectedPrinciple = "";
    renderResult();
  } catch (error) {
    els.error.textContent = String(error.message || error);
    els.error.hidden = false;
    renderStreamingAudit();
  } finally {
    state.isStreaming = false;
    els.button.disabled = false;
    els.button.textContent = "Review";
    if (!state.result) renderStreamingAudit();
  }
}

async function consumeReviewStream(response) {
  if (!response.body) {
    throw new Error("stream_not_available: 이 브라우저에서 응답 스트림을 읽을 수 없습니다.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      handleStreamEvent(JSON.parse(line));
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    handleStreamEvent(JSON.parse(buffer));
  }
}

function handleStreamEvent(event) {
  state.streamEvents.push({ ...event, received_at: new Date().toLocaleTimeString("ko-KR", { hour12: false }) });
  if (event.review_run_id) {
    els.runLabel.textContent = event.review_run_id;
  }
  if (event.event === "result") {
    state.result = event.result;
  }
  renderStreamingAudit();
  if (event.event === "error") {
    throw new Error(formatStreamError(event));
  }
}

function formatStreamError(event) {
  const detail = event.detail || {};
  const title = detail.error || event.error || "review_failed";
  const message = detail.message || event.summary || "심사 워크플로우가 완료되지 못했습니다.";
  const cause = detail.cause ? `\n\n원인: ${detail.cause}` : "";
  return `${title}: ${message}${cause}`;
}

async function formatApiError(response) {
  const fallback = `HTTP ${response.status} ${response.statusText}`;
  const text = await response.text();
  try {
    const payload = JSON.parse(text);
    const detail = payload.detail || payload;
    if (typeof detail === "string") return `${fallback}: ${detail}`;
    const title = detail.error || "review_failed";
    const message = detail.message || "심사 워크플로우가 완료되지 못했습니다.";
    const cause = detail.cause ? `\n\n원인: ${detail.cause}` : "";
    return `${title}: ${message}${cause}`;
  } catch (_error) {
    return text ? `${fallback}: ${text}` : fallback;
  }
}

function renderEmpty() {
  els.verdictHeader.innerHTML = `<div class="verdict-main"><span class="verdict-label">심사 대기</span><p class="verdict-desc">광고 문안을 입력하고 Review를 실행하세요.</p></div>`;
  els.riskStrip.innerHTML = "";
  PRINCIPLES.forEach((principle) => {
    els.riskStrip.appendChild(principleButton(principle, "해당 없음"));
  });
  els.highlightedText.innerHTML = `<div class="empty-state">심사할 광고 원문이 여기에 표시됩니다.</div>`;
  els.highlightSummary.innerHTML = highlightLegend();
  els.conditionalNotice.textContent = "통과 후보도 완전 면책이 아니라 현재 문안 기준의 1차 검토 결과입니다.";
  els.detail.innerHTML = `<div class="empty-state">하이라이트나 Claim 카드를 선택하면 상세 판단이 표시됩니다.</div>`;
  els.overallTab.innerHTML = "";
  els.sentencesTab.innerHTML = "";
  els.claimsTab.innerHTML = "";
  els.graphCanvas.innerHTML = "";
  els.productFactsTab.innerHTML = "";
  renderAudit([]);
}

function renderResult() {
  renderVerdictHeader();
  renderRiskStrip();
  renderHighlights();
  renderOverallContext();
  renderSentenceMap();
  renderClaimCards();
  renderDetail();
  renderGraph();
  renderProductFacts();
  renderAudit(state.streamEvents.length ? state.streamEvents : buildAuditSteps());
}

function renderVerdictHeader() {
  const result = state.result;
  const [label, desc] = VERDICT_LABELS[result.final_verdict] || [result.final_verdict, ""];
  const maxRisk = maxSeverity(result);
  const conditional = conditionalDisclosures(result);
  const trackB = result.overall_impression_judgment || {};
  const hasRetrievalFailure = (result.context_anchors?.length || 0) > 0 && (result.cu_plan?.length || 0) === 0;
  const partialRetrievalFailures = systemReviewItems(result).filter((item) => isActionableAnchor(item.anchor_id)).length;
  const badgeClass = verdictClass(result.final_verdict);
  els.runLabel.textContent = result.review_run_id || "";
  els.verdictHeader.innerHTML = `
    <div class="verdict-main">
      <span class="verdict-label"><span class="badge ${badgeClass}">${label}</span></span>
      <p class="verdict-desc">${escapeHtml(desc)}</p>
      <div class="meta-row">
        ${conditional.length ? `<span class="badge review">조건부 통과 · 유지 고지 ${conditional.length}</span>` : ""}
        ${trackB.misleading_risk_score >= 0.45 ? `<span class="badge review">Track B 오인 ${Number(trackB.misleading_risk_score).toFixed(2)}</span>` : ""}
        ${hasRetrievalFailure ? `<span class="badge review">정책 매칭 실패 · 검토 필요</span>` : ""}
        ${partialRetrievalFailures ? `<span class="badge review">일부 anchor 정책 매칭 실패 ${partialRetrievalFailures}</span>` : ""}
      </div>
    </div>
    ${metricCell("Anchors", result.context_anchors?.length || 0)}
    ${metricCell("CUPlan", result.cu_plan?.length || 0)}
    ${metricCell("Issues", result.detected_issues?.length || 0)}
    ${metricCell("최고 리스크", maxRisk || "0")}
  `;
  els.conditionalNotice.innerHTML = conditional.length
    ? `<strong>유지해야 할 고지</strong><div class="tag-row">${conditional.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}</div>`
    : `통과 후보도 완전 문제 없음이 아니라 현재 문안 기준의 1차 검토 결과입니다. 고지 문구가 있는 경우 삭제하지 마세요.`;
}

function metricCell(label, value) {
  return `<div class="metric-cell"><span class="metric-label">${label}</span><div class="metric-value">${value}</div></div>`;
}

function renderRiskStrip() {
  els.riskStrip.innerHTML = "";
  const statuses = principleStatuses(state.result);
  PRINCIPLES.forEach((principle) => {
    els.riskStrip.appendChild(principleButton(principle, statuses[principle.key] || "해당 없음"));
  });
}

function principleButton(principle, status) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `principle-pill ${state.selectedPrinciple === principle.key ? "is-active" : ""}`;
  button.innerHTML = `<span class="principle-name">${principle.label}</span><span class="principle-status ${statusClass(status)}">${status}</span>`;
  button.addEventListener("click", () => {
    state.selectedPrinciple = state.selectedPrinciple === principle.key ? "" : principle.key;
    renderResult();
  });
  return button;
}

function renderHighlights() {
  const text = els.text.value || "";
  const spans = highlightCandidates(text);
  const rendered = renderAnnotatedText(text, spans);

  els.highlightedText.innerHTML = rendered.html || `<div class="empty-state">광고 원문이 비어 있습니다.</div>`;
  els.highlightSummary.innerHTML = highlightSummary(rendered.visibleSpans, text, rendered.hiddenByOverlap);
  els.highlightedText.querySelectorAll(".hl").forEach((button) => {
    button.addEventListener("click", () => selectAnchor(button.dataset.anchorId));
  });
}

function highlightCandidates(text) {
  const anchors = filteredAnchors();
  const surfaceSpans = anchors
    .map((anchor) => {
      const display = anchorDisplay(anchor.anchor_id);
      const aligned = alignSpan(text, anchor.span);
      const verdict = display?.display_verdict || "ANCHOR";
      const role = display?.display_role || (isActionableAnchor(anchor.anchor_id) ? "actionable" : "scope");
      const className = highlightClass(verdict);
      const cuCount = display?.cu_count || 0;
      return {
        id: anchor.anchor_id,
        anchorId: anchor.anchor_id,
        start: aligned.start,
        end: aligned.end,
        text: anchor.span.text,
        verdict,
        role,
        className,
        roleClass: role === "scope" ? "scope-highlight" : "actionable-highlight",
        label: highlightLabel(anchor, verdict, role, cuCount),
        tooltip: highlightTooltip(anchor, display),
        priority: highlightPriority(verdict, role, anchor.anchor_type, cuCount),
        layer: "claim-surface",
        chipMode: "end",
      };
    })
    .filter((span) => Number.isInteger(span.start) && Number.isInteger(span.end) && span.start >= 0 && span.end <= text.length && span.end > span.start);
  return [...surfaceSpans, ...qualifierHighlightCandidates(text, anchors), ...disclosureHighlightCandidates(text)];
}

function qualifierHighlightCandidates(text, anchors) {
  return anchors.flatMap((anchor) => {
    const display = anchorDisplay(anchor.anchor_id);
    const qualifierVerdict = display?.display_verdict || "ANCHOR";
    return claimQualifiers(anchor.claim_id).map((qualifier) => {
      const aligned = alignSpan(text, qualifier.span || { text: qualifier.text, start: -1, end: -1 });
      const roleClass = qualifier.role === "disclosure_qualifier" ? "mitigation-highlight" : "qualifier-highlight";
      const className = qualifier.role === "disclosure_qualifier" ? "compliant" : highlightClass(qualifierVerdict);
      return {
        id: qualifier.qualifier_id || `${anchor.anchor_id}_${qualifier.text}`,
        anchorId: anchor.anchor_id,
        start: aligned.start,
        end: aligned.end,
        text: qualifier.text,
        verdict: qualifierVerdict,
        role: qualifier.role,
        className,
        roleClass,
        label: QUALIFIER_LABELS[qualifier.role] || "표현",
        tooltip: `${QUALIFIER_LABELS[qualifier.role] || "표현"} · ${qualifier.meaning || qualifier.risk_reason || ""}`,
        priority: qualifierPriority(qualifier, qualifierVerdict),
        layer: "qualifier-token",
        chipMode: "end",
      };
    });
  }).filter((span) => Number.isInteger(span.start) && Number.isInteger(span.end) && span.start >= 0 && span.end <= text.length && span.end > span.start);
}

function disclosureHighlightCandidates(text) {
  const diagnostics = state.result?.prominence_diagnostics || [];
  const checks = state.result?.product_fact_context?.disclosure_checks || [];
  return (state.result?.disclosure_links || []).map((link, index) => {
    const evidence = link.disclosure_text || link.evidence || "";
    const aligned = alignSpan(text, { text: evidence, start: -1, end: -1 });
    const status = link.status || "";
    const diagnostic = diagnostics.find((item) => item.disclosure_sentence_id === link.disclosure_sentence_id || item.evidence === evidence);
    const check = checks.find((item) => item.check_id === link.check_id);
    return {
      id: `disclosure_${link.disclosure_sentence_id || index}`,
      anchorId: anchorForSentence(link.benefit_sentence_id)?.anchor_id || state.selectedAnchorId,
      start: aligned.start,
      end: aligned.end,
      text: evidence,
      verdict: status === "PROMINENCE_INSUFFICIENT" ? "INSUFFICIENT" : "COMPLIANT",
      role: "disclosure",
      className: status === "PROMINENCE_INSUFFICIENT" ? "prominence-warning" : "compliant",
      roleClass: "mitigation-highlight",
      label: status === "PROMINENCE_INSUFFICIENT" ? "고지 있음 · 위계 낮음" : DISCLOSURE_LABELS[link.check_id] || check?.label || "유지 고지",
      tooltip: diagnostic?.message || link.reason || "수정 시 유지해야 할 고지입니다.",
      priority: status === "PROMINENCE_INSUFFICIENT" ? 76 : 58,
      layer: "disclosure-token",
      chipMode: "end",
    };
  }).filter((span) => span.text && Number.isInteger(span.start) && Number.isInteger(span.end) && span.start >= 0 && span.end <= text.length && span.end > span.start);
}

function renderAnnotatedText(text, candidates) {
  if (!text) return { html: "", visibleSpans: [], hiddenByOverlap: 0 };
  const valid = candidates.filter((item) => item.start >= 0 && item.end <= text.length && item.end > item.start);
  const boundaries = new Set([0, text.length]);
  valid.forEach((item) => {
    boundaries.add(item.start);
    boundaries.add(item.end);
  });
  const points = [...boundaries].sort((a, b) => a - b);
  const parts = [];
  const visible = new Map();
  const suppressed = new Map();

  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    if (end <= start) continue;
    const segmentText = text.slice(start, end);
    const active = valid.filter((item) => item.start < end && start < item.end);
    if (!active.length) {
      parts.push(escapeHtml(segmentText));
      continue;
    }
    const top = [...active].sort((a, b) => b.priority - a.priority || layerRank(b.layer) - layerRank(a.layer))[0];
    active.forEach((item) => {
      if (item.id === top.id) visible.set(item.id, item);
      else suppressed.set(item.id, item);
    });
    const classes = [
      "hl",
      top.className,
      top.roleClass,
      top.layer,
      top.anchorId === state.selectedAnchorId ? "is-selected" : "",
      top.className === "prominence-warning" ? "has-prominence-gap" : "",
    ].filter(Boolean).join(" ");
    const segmentEnd = top.end === end;
    const hiddenEnding = active.filter((item) => item.id !== top.id && item.end === end).length;
    const chip = segmentEnd ? `<span class="hl-chip">${escapeHtml(top.label)}${hiddenEnding ? ` +${hiddenEnding}` : ""}</span>` : "";
    parts.push(
      `<button class="${classes}" data-anchor-id="${escapeHtml(top.anchorId || "")}" title="${escapeHtml(top.tooltip)}" type="button"><span class="hl-text">${escapeHtml(segmentText)}</span>${chip}</button>`
    );
  }

  return {
    html: parts.join(""),
    visibleSpans: [...visible.values()].sort((a, b) => a.start - b.start || b.priority - a.priority),
    hiddenByOverlap: suppressed.size,
  };
}

function layerRank(layer) {
  return { "qualifier-token": 3, "disclosure-token": 2, "claim-surface": 1 }[layer] || 0;
}

function highlightPriority(verdict, role, anchorType, cuCount) {
  if (role === "scope") return 5;
  const verdictScore = { NON_COMPLIANT: 90, RETRIEVAL_FAILURE: 80, INSUFFICIENT: 70, COMPLIANT: 40, NOT_APPLICABLE: 30, ANCHOR: 20 }[verdict] || 20;
  const typeScore = anchorType === "risk_anchor" ? 12 : anchorType === "claim_anchor" ? 10 : 0;
  return verdictScore + typeScore + Math.min(Number(cuCount || 0), 5);
}

function qualifierPriority(qualifier, verdict) {
  const roleScore = {
    guarantee: 98,
    certainty: 96,
    condition_scope: 92,
    target_scope: 90,
    risk_downplay: 88,
    benefit_scope: 82,
    comparison: 78,
    disclosure_qualifier: 58,
    other: 50,
  }[qualifier.role] || 50;
  const verdictBonus = verdict === "NON_COMPLIANT" ? 8 : verdict === "INSUFFICIENT" ? 4 : 0;
  return roleScore + verdictBonus;
}

function highlightLabel(anchor, verdict, role, cuCount) {
  if (role === "scope") return "범위";
  const human = humanAnchorLabel(anchor);
  if (verdict === "NON_COMPLIANT") return human || "위험 표현";
  if (verdict === "RETRIEVAL_FAILURE") return "매칭 실패";
  if (verdict === "INSUFFICIENT") return "검토";
  if (verdict === "COMPLIANT" || verdict === "NOT_APPLICABLE") return "완화";
  return human || (cuCount ? "검토 문구" : "검토됨");
}

function humanAnchorLabel(anchor) {
  const featureSet = anchor.feature_set || (state.result?.anchor_feature_sets || []).find((item) => item.anchor_id === anchor.anchor_id) || {};
  const action = (featureSet.action_types || []).find((item) => HUMAN_ACTION_LABELS[item]);
  if (action) return HUMAN_ACTION_LABELS[action];
  const feature = (featureSet.positive_features || []).find((item) => HUMAN_FEATURE_LABELS[item]);
  if (feature) return HUMAN_FEATURE_LABELS[feature];
  const qualifier = claimQualifiers(anchor.claim_id).find((item) => QUALIFIER_LABELS[item.role]);
  if (qualifier) return QUALIFIER_LABELS[qualifier.role];
  return "";
}

function highlightTooltip(anchor, display) {
  const hypernyms = (anchor.hypernyms || []).map((item) => item.hypernym).slice(0, 3).join(", ");
  const verdict = JUDGMENT_STATUS[display?.display_verdict] || display?.display_verdict || "검토됨";
  const role = display?.display_role === "scope" ? "범위 정보" : "판단 대상";
  const basis = policyBasisForAnchor(anchor).slice(0, 2).join(", ");
  return `${role} · ${verdict}${hypernyms ? ` · ${hypernyms}` : ""}${basis ? ` · 근거 ${basis}` : ""}`;
}

function highlightSummary(spans, text, hiddenByOverlap = 0) {
  if (!state.result) return highlightLegend();
  const totalActionable = (state.result.anchor_display || []).filter((item) => item.display_role === "actionable").length;
  return `
    <div class="highlight-meta">
      <span>원문 ${text.length}자</span>
      <span>표시 ${spans.length}</span>
      <span>판단 anchor ${totalActionable}</span>
      ${hiddenByOverlap ? `<span>겹침 정리 ${hiddenByOverlap}</span>` : ""}
      ${state.selectedPrinciple ? `<span>필터 ${escapeHtml(PRINCIPLES.find((item) => item.key === state.selectedPrinciple)?.label || "")}</span>` : ""}
    </div>
    ${highlightLegend()}
  `;
}

function highlightLegend() {
  return `
    <div class="highlight-legend" aria-label="하이라이트 범례">
      <span><i class="legend-line non-compliant"></i>위반 의심</span>
      <span><i class="legend-line insufficient"></i>검토 필요</span>
      <span><i class="legend-line compliant"></i>유지 고지</span>
      <span><i class="legend-line prominence-warning"></i>고지 있음 · 위계 낮음</span>
      <span><i class="legend-dot anchor-only"></i>범위/검토됨</span>
    </div>
  `;
}

function renderOverallContext() {
  const frame = state.result?.context_frame || {};
  const influences = state.result?.context_influences || [];
  if (!state.result) {
    els.overallTab.innerHTML = `<div class="empty-state">Review를 실행하면 전체 광고 인상과 문장 영향이 여기에 표시됩니다.</div>`;
    return;
  }
  els.overallTab.innerHTML = `
    <section class="context-frame-grid">
      <article class="detail-card context-frame-card">
        <div class="card-top">
          <h3>ContextFrame</h3>
          <span class="badge ${trackBBadgeClass({ verdict: frame.overall_risk_level, misleading_risk_score: frame.overall_risk_level === "HIGH" ? 1 : frame.overall_risk_level === "MEDIUM" ? 0.55 : 0.2 })}">${escapeHtml(frame.overall_risk_level || "UNKNOWN")}</span>
        </div>
        <p class="evidence-text">
          <b>요약</b><br />${escapeHtml(frame.summary || "-")}<br /><br />
          <b>핵심 메시지</b><br />${escapeHtml(frame.primary_message || "-")}<br /><br />
          <b>대표 소비자 인상</b><br />${escapeHtml(frame.representative_consumer_impression || "-")}
        </p>
      </article>
      <article class="detail-card">
        <h3>광고 목적 / 톤 / 위험 축</h3>
        <div class="tag-row">
          <span class="tag">목적 ${escapeHtml(frame.product_purpose || "-")}</span>
          <span class="tag">톤 ${escapeHtml(frame.tone || "-")}</span>
        </div>
        <div class="tag-row">${(frame.risk_axes || []).map((axis) => `<span class="tag">${escapeHtml(axis)}</span>`).join("") || `<span class="tag">위험 축 없음</span>`}</div>
        <p class="evidence-text">이 레이어는 광고 전체를 먼저 읽고, 문장별 판단이 전체 인상에 어떻게 기여하는지 judge evidence window에 전달합니다.</p>
      </article>
    </section>
    <section class="detail-card">
      <h3>ContextInfluence</h3>
      <div class="sentence-relation-list">
        ${influences.length ? influences.map((item) => `
          <article class="sentence-relation-card">
            <div class="card-top">
              <strong>${escapeHtml(item.influence_type || "influence")}</strong>
              <span class="tag">${escapeHtml(item.risk_delta || "NEUTRAL")} · ${Number(item.confidence || 0).toFixed(2)}</span>
            </div>
            <p class="evidence-text">${escapeHtml(item.effect || "-")}</p>
          </article>
        `).join("") : `<div class="empty-state">문장/표현이 전체 인상에 미치는 영향이 추출되지 않았습니다.</div>`}
      </div>
    </section>
  `;
}

function renderSentenceMap() {
  const sentences = state.result?.sentence_units || [];
  const relations = state.result?.inter_sentence_relations || [];
  if (!state.result) {
    els.sentencesTab.innerHTML = `<div class="empty-state">Review를 실행하면 SentenceUnit과 문장 간 관계가 여기에 표시됩니다.</div>`;
    return;
  }
  els.sentencesTab.innerHTML = `
    <section class="sentence-map">
      <article class="sentence-column">
        <h3>SentenceUnit</h3>
        ${sentences.length ? sentences.map(sentenceCard).join("") : `<div class="empty-state">문장 단위가 없습니다.</div>`}
      </article>
      <article class="sentence-column">
        <h3>InterSentenceRelation</h3>
        ${relations.length ? relations.map(sentenceRelationCard).join("") : `<div class="empty-state">문장 간 관계가 없습니다.</div>`}
      </article>
    </section>
  `;
  els.sentencesTab.querySelectorAll("[data-anchor-id]").forEach((button) => {
    button.addEventListener("click", () => selectAnchor(button.dataset.anchorId));
  });
}

function sentenceCard(sentence) {
  const claims = claimsForSentence(sentence.sentence_id);
  return `
    <article class="sentence-card">
      <div class="card-top">
        <strong>${escapeHtml(sentence.text || "-")}</strong>
        <span class="badge ${trackBBadgeClass({ verdict: sentence.risk_level, misleading_risk_score: sentence.risk_level === "HIGH" ? 1 : sentence.risk_level === "MEDIUM" ? 0.55 : 0.2 })}">${escapeHtml(sentence.role || "other")}</span>
      </div>
      <p class="evidence-text">
        <b>문장 의미</b><br />${escapeHtml(sentence.local_meaning || "-")}<br /><br />
        <b>전체 맥락 영향</b><br />${escapeHtml(sentence.context_effect || "-")}
      </p>
      <div class="tag-row">
        ${claims.length ? claims.map((claim) => {
          const anchor = anchorForClaim(claim.claim_id);
          return anchor ? `<button class="tag tag-button-inline" data-anchor-id="${anchor.anchor_id}" type="button">${escapeHtml(claim.text)}</button>` : `<span class="tag">${escapeHtml(claim.text)}</span>`;
        }).join("") : `<span class="tag">독립 Claim 없음</span>`}
      </div>
    </article>
  `;
}

function sentenceRelationCard(relation) {
  const source = sentenceById(relation.source_sentence_id);
  const target = sentenceById(relation.target_sentence_id);
  return `
    <article class="sentence-relation-card">
      <div class="card-top">
        <strong>${escapeHtml(relation.relation_type || "OTHER")}</strong>
        <span class="tag">문장 간 영향</span>
      </div>
      <p class="evidence-text">
        <b>From</b><br />${escapeHtml(source?.text || relation.source_sentence_id || "-")}<br /><br />
        <b>To</b><br />${escapeHtml(target?.text || relation.target_sentence_id || "-")}<br /><br />
        <b>Why</b><br />${escapeHtml(relation.explanation || "-")}<br /><br />
        <b>Evidence</b><br />${escapeHtml(relation.evidence || "-")}
      </p>
    </article>
  `;
}

function renderClaimCards() {
  const anchors = filteredAnchors();
  els.claimsTab.innerHTML = anchors
    .map((anchor) => {
      const display = anchorDisplay(anchor.anchor_id);
      const score = display?.score ? Number(display.score).toFixed(2) : "-";
      const cuCount = display?.cu_count ?? anchorPlanCount(anchor.anchor_id);
      const displayVerdict = display?.display_verdict || "ANCHOR";
      const cardClass = display?.display_role === "scope" ? " is-scope" : "";
      const failureCode = display?.retrieval_failure_code && display.retrieval_failure_code !== "MATCHED" ? display.retrieval_failure_code : "";
      const qualifiers = claimQualifiers(anchor.claim_id);
      return `
        <article class="claim-card${cardClass} ${state.selectedAnchorId === anchor.anchor_id ? "is-selected" : ""}" data-anchor-id="${anchor.anchor_id}">
          <div class="card-top">
            <div>
              <div class="span-text">${escapeHtml(anchor.span.text)}</div>
              <div class="meta-row">
                <span class="tag">${escapeHtml(anchor.anchor_type)}</span>
                <span class="tag">CU ${cuCount}</span>
                <span class="tag">${score}</span>
                ${failureCode ? `<span class="tag">${escapeHtml(failureCode)}</span>` : ""}
              </div>
            </div>
            <span class="badge ${judgmentBadgeClass(displayVerdict)}">${JUDGMENT_STATUS[displayVerdict] || "검토됨"}</span>
          </div>
          <div class="tag-row">
            ${anchor.hypernyms.map((item) => `<span class="tag">${escapeHtml(item.hypernym)}</span>`).join("")}
            ${qualifiers.map((item) => `<span class="tag qualifier-tag">${escapeHtml(item.text)} · ${escapeHtml(item.role)}</span>`).join("")}
          </div>
        </article>
      `;
    })
    .join("");
  els.claimsTab.querySelectorAll(".claim-card").forEach((card) => {
    card.addEventListener("click", () => selectAnchor(card.dataset.anchorId));
  });
}

function renderDetail() {
  const anchor = state.result?.context_anchors?.find((item) => item.anchor_id === state.selectedAnchorId);
  if (!anchor) {
    els.detail.innerHTML = `<div class="empty-state">선택된 anchor가 없습니다.</div>`;
    return;
  }
  const judgments = judgmentsForAnchor(anchor.anchor_id);
  const effective = effectiveJudgmentsForAnchor(anchor.anchor_id);
  const planItems = state.result.cu_plan.filter((item) => item.anchor_id === anchor.anchor_id);
  const exceptions = state.result.exception_reviews.filter((review) =>
    judgments.some((judgment) => judgment.judgment_id === review.judgment_id)
  );
  const issues = state.result.detected_issues.filter((issue) => effective.some((judgment) => judgment.cu_id === issue.risk_code));
  const display = anchorDisplay(anchor.anchor_id);
  els.detail.innerHTML = `
    <section class="detail-card">
      <h3>${escapeHtml(anchor.span.text)}</h3>
      <div class="meta-row">
        <span class="tag">${display?.display_role === "scope" ? "범위 정보" : display?.display_role === "mitigation" ? "고지/완화 근거" : "심사 대상 문구"}</span>
        ${anchor.hypernyms.slice(0, 4).map((item) => `<span class="tag">${escapeHtml(item.hypernym)}</span>`).join("")}
      </div>
      ${issueSummaryPanel(anchor, effective, issues)}
    </section>
    <section class="detail-card">
      <h3>문제 표현</h3>
      ${claimQualifierPanel(anchor) || `<div class="empty-state">별도 qualifier 없이 문장 전체를 검토합니다.</div>`}
    </section>
    <section class="detail-card">
      <h3>상품 사실 대조</h3>
      ${productFactComparisonPanel(anchor)}
    </section>
    <section class="detail-card">
      <h3>법적 / 정책 근거</h3>
      ${policyEvidenceChainPanel(anchor)}
    </section>
    <section class="detail-card">
      <h3>필요한 고지</h3>
      ${productDisclosurePanel(anchor)}
    </section>
    <section class="detail-card">
      <h3>소비자 오인 판단</h3>
      ${overallImpressionPanel(anchor)}
    </section>
    <section class="detail-card">
      <h3>예외 / 완화 검토</h3>
      ${exceptionPanel(anchor, exceptions)}
    </section>
    <section class="detail-card">
      <h3>수정 제안</h3>
      ${revisionPanel(anchor, issues, effective, display)}
    </section>
    <section class="detail-card">
      <details>
        <summary>Debug · 내부 id / feature / raw evidence</summary>
        ${anchorFeaturePanel(anchor)}
        <details>
          <summary>Context facts</summary>
          <div class="evidence-text">${anchor.facts.map(escapeHtml).join("<br />") || "없음"}</div>
        </details>
        <h3>CU별 판단</h3>
        ${
          effective.length
            ? effective.map((judgment) => judgmentCard(judgment, planItems.find((item) => item.plan_item_id === judgment.plan_item_id), rawJudgment(judgment.judgment_id))).join("")
            : planItems.length
              ? `<div class="empty-state">CUPlan은 생성됐지만 이 anchor에 대한 judgment가 없습니다. LLM judgment 단계를 확인하세요.</div>`
              : `<div class="empty-state">이 anchor에 매칭된 CU가 없습니다. 정책 매칭 실패로 검토 필요 상태입니다.</div>`
        }
        <h3>조항 / 원칙 집계</h3>
        ${policyAggregationPanel(anchor)}
      </details>
    </section>
  `;
}

function issueSummaryPanel(anchor, judgments, issues) {
  const risky = judgments.filter((item) => ["NON_COMPLIANT", "INSUFFICIENT"].includes(item.verdict));
  if (!risky.length && displayRoleForAnchor(anchor) === "mitigation") {
    return `<p class="evidence-text">이 문구는 조건이나 제한사항을 보완하는 완화 근거로 사용됩니다.</p>`;
  }
  if (!risky.length) {
    return `<p class="evidence-text">선택 문구 기준 중대한 위반 판단은 없지만, 상품 사실과 필수고지 상태는 별도로 확인해야 합니다.</p>`;
  }
  const first = issues[0] || {};
  return `
    <p class="evidence-text">${escapeHtml(first.rationale || risky[0].why || "이 문구는 소비자 오인 가능성이 있어 수정 또는 추가 고지가 필요합니다.")}</p>
    <div class="meta-row">
      <span class="badge ${judgmentBadgeClass(risky[0].verdict)}">${JUDGMENT_STATUS[risky[0].verdict] || risky[0].verdict}</span>
      ${first.source_article ? `<span class="tag">${escapeHtml(first.source_article)}</span>` : ""}
      ${first.risk_title ? `<span class="tag">${escapeHtml(first.risk_title)}</span>` : ""}
    </div>
  `;
}

function displayRoleForAnchor(anchor) {
  return anchorDisplay(anchor.anchor_id)?.display_role || "actionable";
}

function policyAggregationPanel(anchor) {
  const articleRows = aggregationRowsForAnchor(state.result?.article_aggregation || [], anchor);
  const principleRows = aggregationRowsForAnchor(state.result?.principle_aggregation || [], anchor);
  const rows = [...articleRows, ...principleRows.filter((row) => !articleRows.some((item) => item.key === row.key))];
  if (!rows.length) return `<div class="empty-state">이 anchor가 조항/원칙 집계에 아직 연결되지 않았습니다.</div>`;
  return `
    <div class="aggregation-list">
      ${rows.map((row) => `
        <article class="aggregation-card">
          <div class="card-top">
            <strong>${escapeHtml(policyAggregationTitle(row))}</strong>
            <span class="badge ${judgmentBadgeClass(row.effective_verdict)}">${JUDGMENT_STATUS[row.effective_verdict] || row.effective_verdict}</span>
          </div>
          <div class="meta-row">
            <span class="tag">${escapeHtml(row.axis || "policy")}</span>
            <span class="tag">CU ${Number(row.cu_count || 0)}</span>
            <span class="tag">issue ${Number(row.issue_count || 0)}</span>
            <span class="tag">max ${Number(row.max_score || 0).toFixed(2)}</span>
            ${(row.principles || []).map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}
          </div>
          <p class="evidence-text">
            <b>관련 문구</b><br />${(row.anchor_spans || []).map(escapeHtml).join("<br />") || "-"}<br /><br />
            <b>연결 CU</b><br />${(row.cu_titles || []).map(escapeHtml).join("<br />") || "-"}
          </p>
        </article>
      `).join("")}
    </div>
  `;
}

function policyAggregationTitle(row) {
  if (row.axis === "article") return `${row.key || "근거 조항"} 기준 최종 영향`;
  return `${row.key || "원칙 미상"} 원칙 기준 최종 영향`;
}

function aggregationRowsForAnchor(rows, anchor) {
  return (rows || []).filter((row) => (row.anchor_spans || []).includes(anchor.span.text));
}

function policyEvidenceChainPanel(anchor) {
  const chains = state.result?.policy_evidence_chains || {};
  const legal = chainsForAnchor(chains.legal_basis_chains, anchor.anchor_id).filter((chain) => chain.status === "FOUND");
  const disclosures = chainsForAnchor(chains.disclosure_chains, anchor.anchor_id).filter((chain) => chain.status === "FOUND");
  const exceptions = chainsForAnchor(chains.exception_chains, anchor.anchor_id).filter((chain) => chain.status === "FOUND");
  const fallbackRows = (state.result?.reference_paths_summary || []).filter((row) => row.anchor_id === anchor.anchor_id);
  if (!legal.length && !disclosures.length && !exceptions.length && !fallbackRows.length) {
    return `<div class="empty-state">이 anchor의 목적별 근거 chain이 없습니다. 부족한 chain은 Audit/Trace 진단에 모았습니다.</div>`;
  }
  return `
    <div class="policy-chain-grid">
      ${chainGroup("법적 근거 · Legal basis", "어떤 금소법/시행령/감독규정/심의기준 근거에서 왔는가", legal, "basis_nodes")}
      ${chainGroup("필수 고지 · Required disclosure", "문안에 무엇을 보완하거나 유지해야 하는가", disclosures, "disclosure_nodes")}
      ${chainGroup("예외/완화 · Exception", "어떤 고지/상품사실/승인 근거가 있으면 완화 가능한가", exceptions, "exception_nodes", "현재 문안 기준 명시적 예외/완화 chain 없음")}
      ${!legal.length && fallbackRows.length ? fallbackReferenceRows(fallbackRows) : ""}
    </div>
  `;
}

function chainsForAnchor(rows, anchorId) {
  return (rows || []).filter((chain) => chain.anchor_id === anchorId);
}

function chainGroup(title, subtitle, rows, nodeKey, emptyText = "FOUND chain 없음") {
  return `
    <article class="reference-path-card">
      <div class="card-top">
        <strong>${escapeHtml(title)}</strong>
        <span class="tag">${rows.length ? `${rows.length} found` : "not found"}</span>
      </div>
      <p class="evidence-text">${escapeHtml(subtitle)}</p>
      ${
        rows.length
          ? rows
              .map(
                (chain) => `
                <div class="chain-item">
                  <strong>${escapeHtml(chain.summary || chain.chain_type || title)}</strong>
                  <div class="tag-row">
                    ${(chain[nodeKey] || []).map((node) => `<span class="tag">${escapeHtml(chainNodeLabel(node))}</span>`).join("")}
                  </div>
                  ${
                    (chain.provenance_snippets || []).length
                      ? `<details><summary>Provenance snippets</summary><p class="evidence-text">${chain.provenance_snippets
                          .map((item) => escapeHtml(shorten(item.text || item.summary || "", 360)))
                          .join("<hr />")}</p></details>`
                      : ""
                  }
                </div>
              `
              )
              .join("")
          : `<div class="empty-state">${escapeHtml(emptyText)}</div>`
      }
    </article>
  `;
}

function chainNodeLabel(node) {
  if (!node) return "-";
  return node.title || node.name || node.label || node.article || node.id || JSON.stringify(node);
}

function fallbackReferenceRows(rows) {
  return `
    <div class="reference-path-list">
      ${rows.map((row) => `
        <article class="reference-path-card">
          <div class="card-top">
            <strong>${escapeHtml(row.risk_title || row.cu_id || "CU 근거")}</strong>
            <span class="tag">${escapeHtml(row.source_article || "조항 미상")}</span>
          </div>
          <div class="meta-row">
            <span class="tag">${escapeHtml(row.principle || "원칙 미상")}</span>
            ${row.has_disclosure_evidence ? `<span class="tag">필수고지 evidence</span>` : ""}
            ${row.has_exception_path ? `<span class="tag">exception path</span>` : ""}
          </div>
          <p class="evidence-text">
            <b>Traversal</b><br />${(row.path_labels || []).map(escapeHtml).join(" → ") || "CU → Premise/LegalChunk evidence"}<br /><br />
            <b>Evidence</b><br />${(row.legal_evidence || []).map((item) => `${escapeHtml(item.id || "")}<br />${escapeHtml(shorten(item.text || "", 360))}`).join("<hr />") || "-"}
          </p>
        </article>
      `).join("")}
    </div>
  `;
}

function judgmentCard(judgment, planItem, raw) {
  const evidence = planItem?.evidence_texts || [];
  const rawTag = raw && raw.verdict !== judgment.verdict ? `<span class="tag">raw ${escapeHtml(raw.verdict)}</span>` : "";
  return `
    <article class="judgment-card">
      <div class="card-top">
        <strong>${escapeHtml(legalJudgmentTitle(planItem, judgment))}</strong>
        <span class="badge ${judgmentBadgeClass(judgment.verdict)}">${JUDGMENT_STATUS[judgment.verdict] || judgment.verdict}</span>
      </div>
      <div class="meta-row">
        <span class="tag">${escapeHtml(planItem?.principle || "원칙 미상")}</span>
        ${planItem?.source_article ? `<span class="tag">${escapeHtml(planItem.source_article)}</span>` : ""}
        <span class="tag">score ${Number(judgment.score || 0).toFixed(2)}</span>
        ${rawTag}
      </div>
      <p class="evidence-text">${escapeHtml(judgment.why)}</p>
      <details>
        <summary>근거 / Evidence window / Debug</summary>
        <div class="evidence-text">
          <strong>cu_id</strong><br />${escapeHtml(judgment.cu_id || "-")}<br /><br />
          <strong>action_type</strong><br />${escapeHtml(planItem?.legal_element_profile?.action_type || "-")}<br /><br />
          <strong>matched_features</strong><br />${(planItem?.matched_required_features || []).map(escapeHtml).join("<br />") || "-"}<br /><br />
          <strong>evidence_span</strong><br />${escapeHtml(judgment.evidence_span || "-")}<br /><br />
          <strong>used_policy_evidence</strong><br />${(judgment.used_policy_evidence || []).map(escapeHtml).join("<br />") || "-"}<br /><br />
          <strong>Premise / LegalChunk</strong><br />${evidence.map((item) => escapeHtml(shorten(item, 520))).join("<hr />") || "-"}
        </div>
      </details>
    </article>
  `;
}

function exceptionPanel(anchor, exceptions) {
  const disclosures = disclosureSignals(anchor);
  const blocks = [];
  if (disclosures.length) {
    blocks.push(`<div class="tag-row">${disclosures.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}</div>`);
  }
  if (exceptions.length) {
    blocks.push(
      exceptions
        .map(
          (review) => `
          <article class="exception-card">
            <div class="card-top"><strong>${escapeHtml(review.effect)}</strong><span class="tag">${review.applies ? "applies" : "not applied"}</span></div>
            <p class="evidence-text">${escapeHtml(review.why)}</p>
          </article>
        `
        )
        .join("")
    );
  }
  if (!blocks.length) {
    blocks.push(`<div class="empty-state">명시적 예외/고지 완화 신호가 없습니다.</div>`);
  }
  return blocks.join("");
}

function revisionPanel(anchor, issues, judgments, display) {
  if (display?.display_role === "scope") {
    return `<article class="revision-card"><strong>범위 정보</strong><p class="evidence-text">이 anchor는 상품군, 고객군, 채널 같은 심사 범위를 잡기 위한 정보입니다. 문안 수정 제안은 Claim/Risk anchor에서 생성됩니다.</p></article>`;
  }
  const suggestion = revisionSuggestion(anchor.anchor_id);
  if (suggestion) {
    return revisionSuggestionCard(suggestion);
  }
  if (display?.system_review_required) {
    const diagnostic = display.retrieval_diagnostic || {};
    return `<article class="revision-card"><strong>정책 매칭 보완 필요 · ${escapeHtml(display.retrieval_failure_code || "CU_PLAN_EMPTY")}</strong><p class="evidence-text">${escapeHtml(display.system_review_reason || "이 표현은 정책어로 정규화됐지만 후보 CU가 생성되지 않았습니다.")}<br /><br />candidate ${Number(diagnostic.candidate_count || 0)} · active ${Number(diagnostic.active_candidate_count || 0)} · hypernym ${Number(diagnostic.hypernym_count || 0)}</p></article>`;
  }
  const risky = judgments.filter((item) => ["NON_COMPLIANT", "INSUFFICIENT"].includes(item.verdict));
  if (!risky.length && conditionalDisclosures(state.result).length) {
    return `<article class="revision-card"><strong>고지 유지 필요</strong><p class="evidence-text">현재 통과 후보 판단은 조건/보호한도/상품 설명 관련 고지 문구가 유지된다는 전제입니다.</p></article>`;
  }
  if (!risky.length) {
    return `<div class="empty-state">수정 제안이 필요한 위험 판단이 없습니다.</div>`;
  }
  const nonCompliant = risky.filter((item) => item.verdict === "NON_COMPLIANT");
  if (!nonCompliant.length) {
    return `
      <article class="revision-card">
        <strong>추가 근거 확인 필요</strong>
        <p class="evidence-text">이 anchor는 현재 위반 확정이 아니라 근거/정책 매칭/고지 충족 여부 확인 대상으로 분류됐습니다. 문구를 바로 대체하기보다 관련 상품조건, 필수고지, 조문 근거를 확인하세요.</p>
      </article>
      ${issues.map((issue) => `<article class="revision-card"><strong>${escapeHtml(issue.required_action || "확인 필요")}</strong><p class="evidence-text">${escapeHtml(issue.rationale || "")}</p></article>`).join("")}
    `;
  }
  const after = safeAlternative(anchor.span.text);
  return `
    ${issues.map((issue) => `<article class="revision-card"><strong>${escapeHtml(issue.required_action || "문안 수정 필요")}</strong><p class="evidence-text">${escapeHtml(issue.rationale || "")}</p></article>`).join("")}
    <article class="revision-card">
      <strong>대체 문안 예시</strong>
      <p class="evidence-text"><b>Before</b><br />${escapeHtml(anchor.span.text)}<br /><br /><b>After</b><br />${escapeHtml(after)}</p>
    </article>
  `;
}

function legalJudgmentTitle(planItem, judgment) {
  if (!planItem) return "CU 근거 확인 필요";
  if (planItem.risk_title) {
    return `${planItem.risk_title} · ${planItem.source_article || planItem.principle || "법적 근거 확인"}`;
  }
  const article = planItem.source_article || "근거 조항";
  const subject = planItem.subject || "광고 표현";
  const constraint = planItem.constraint || planItem.context || judgment.cu_id || "준수 여부";
  return `${article} 근거: ${subject} · ${constraint}`;
}

function anchorFeaturePanel(anchor) {
  const featureSet = anchor.feature_set || (state.result?.anchor_feature_sets || []).find((item) => item.anchor_id === anchor.anchor_id);
  if (!featureSet) return "";
  return `
    <details open>
      <summary>금소법 행위요건 feature</summary>
      <div class="tag-row">
        ${(featureSet.action_types || []).map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}
        ${(featureSet.positive_features || []).map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}
      </div>
      <div class="evidence-text">${(featureSet.evidence || []).map(escapeHtml).join("<br />") || "feature evidence 없음"}</div>
    </details>
  `;
}

function revisionSuggestionCard(suggestion) {
  return `
    <article class="revision-card">
      <strong>${escapeHtml(suggestion.severity)} · 수정 제안</strong>
      <p class="evidence-text">
        <b>위험 표현</b><br />${escapeHtml(suggestion.risky_text)}<br /><br />
        <b>왜 문제인지</b><br />${escapeHtml(suggestion.why_problematic)}<br /><br />
        <b>필요 고지</b><br />${(suggestion.required_disclosures || []).map(escapeHtml).join("<br />") || "-"}<br /><br />
        <b>Before</b><br />${escapeHtml(suggestion.before)}<br /><br />
        <b>After</b><br />${escapeHtml(suggestion.after)}<br /><br />
        <b>Reviewer note</b><br />${escapeHtml(suggestion.notes_for_reviewer || "-")}
      </p>
    </article>
  `;
}

function overallImpressionPanel(anchor) {
  const trackB = state.result?.overall_impression_judgment || {};
  if (!trackB.verdict) return `<div class="empty-state">Track B 판단 결과가 없습니다.</div>`;
  const related = (trackB.evidence_paths || []).filter((path) => path.claim_id === anchor.claim_id);
  return `
    <article class="judgment-card">
      <div class="card-top">
        <strong>${escapeHtml(trackB.standard || "전체적 인상 기준")}</strong>
        <span class="badge ${trackBBadgeClass(trackB)}">${escapeHtml(trackB.verdict)} · ${Number(trackB.misleading_risk_score || 0).toFixed(2)}</span>
      </div>
      <p class="evidence-text">
        <b>대표 소비자 인상</b><br />${escapeHtml(trackB.representative_consumer_impression || "-")}<br /><br />
        <b>판단 이유</b><br />${escapeHtml(trackB.why || "-")}<br /><br />
        <b>오인 요인</b><br />${(trackB.misleading_factors || []).map(escapeHtml).join("<br />") || "-"}
      </p>
      <details ${related.length ? "open" : ""}>
        <summary>Context Graph evidence path</summary>
        <div class="evidence-text">
          ${(related.length ? related : trackB.evidence_paths || []).map((path) => `
            <b>${escapeHtml(path.path || "Claim -> Meaning -> Implicature -> ConsumerEffect")}</b><br />
            Claim: ${escapeHtml(path.claim || "-")}<br />
            Meaning: ${escapeHtml(path.meaning || "-")}<br />
            Implicature: ${escapeHtml(path.implicature || "-")}<br />
            ConsumerEffect: ${escapeHtml(path.consumer_effect || "-")}
          `).join("<hr />") || "-"}
        </div>
      </details>
    </article>
  `;
}

function claimQualifierPanel(anchor) {
  const qualifiers = claimQualifiers(anchor.claim_id);
  if (!qualifiers.length) return "";
  return `
    <details open>
      <summary>Claim 내부 표현 / Qualifiers</summary>
      <div class="qualifier-list">
        ${qualifiers
          .map(
            (item) => `
              <article class="qualifier-card">
                <strong>${escapeHtml(item.text)}</strong>
                <div class="meta-row">
                  <span class="tag">${escapeHtml(item.role)}</span>
                  <span class="tag">${escapeHtml(item.prominence_tier || "unknown")}</span>
                  <span class="tag">${Number(item.confidence || 0).toFixed(2)}</span>
                </div>
                <p class="evidence-text">${escapeHtml(item.meaning || "")}<br />${escapeHtml(item.risk_reason || "")}</p>
              </article>
            `
          )
          .join("")}
      </div>
    </details>
  `;
}

function productDisclosurePanel(anchor) {
  const context = state.result?.product_context || {};
  const factContext = state.result?.product_fact_context || {};
  const requirements = state.result?.disclosure_requirements || [];
  const products = context.matched_products || [];
  const comparisonSummary = productFactSummary(factContext);
  const disclosureChecks = factContext.disclosure_checks || [];
  const prominenceDiagnostics = state.result?.prominence_diagnostics || [];
  return `
    <article class="judgment-card">
      <div class="meta-row">
        <span class="tag">상품군 ${escapeHtml(context.product_group || "auto")}</span>
        <span class="tag">상품 ${products.length}</span>
        <span class="tag">문서 ${Number(context.document_count || 0)}</span>
        <span class="tag">본문 fact ${escapeHtml(factContext.extraction_status || "NOT_RUN")}</span>
      </div>
      <details open>
        <summary>본문 fact 대조 상태</summary>
        <div class="evidence-text">
          <b>matched_product</b><br />${escapeHtml(factContext.matched_product || "상품 선택 필요")}<br /><br />
          <b>comparison</b><br />
          ${Object.entries(comparisonSummary)
            .map(([status, count]) => `${escapeHtml(status)} ${escapeHtml(count)}`)
            .join("<br />") || "-"}<br /><br />
          <b>prominence</b><br />
          ${prominenceDiagnostics.length ? prominenceDiagnostics.map((item) => `${escapeHtml(item.diagnostic_code)} · ${escapeHtml(item.message)}`).join("<br />") : "현저성 진단 없음"}<br /><br />
          ${escapeHtml(factContext.reason || "")}
        </div>
      </details>
      <details open>
        <summary>필요 고지 후보</summary>
        <div class="evidence-text">
          ${
            disclosureChecks.length
              ? `<div class="tag-row">${disclosureChecks.map((item) => `<span class="tag ${item.present ? "status-ok" : "status-review"}">${escapeHtml(item.label)} · ${item.present ? "있음" : "누락"}</span>`).join("")}</div><hr />`
              : ""
          }
          ${requirements.map((item) => `<b>${escapeHtml(item.label)}</b> · ${escapeHtml(item.source)}<br />${escapeHtml(item.why)}`).join("<hr />") || "-"}
        </div>
      </details>
      <details>
        <summary>ProductDocument grounding · Debug</summary>
        <div class="evidence-text">
          ${products.map((item) => `<b>${escapeHtml(item.product)}</b><br />${escapeHtml(item.major)} / ${escapeHtml(item.subcategory)} / ${escapeHtml(item.category)}<br />문서 ${Number(item.document_count || 0)} · ${(item.document_labels || []).map(escapeHtml).join(", ")}`).join("<hr />") || "광고 문안과 직접 매칭된 상품명은 없습니다. 상품군 기준 고지 후보만 사용합니다."}
        </div>
      </details>
      <p class="evidence-text">Product Fact Graph는 리뷰 대상 상품이 명확할 때 관련 PDF 본문에서 핵심 상품사실을 추출하고, 광고 ClaimFact와 비교합니다. 상품이 모호하면 사실을 추정하지 않고 상품 선택 필요 상태로 둡니다.</p>
    </article>
  `;
}

function productFactComparisonPanel(anchor) {
  const factContext = state.result?.product_fact_context || {};
  const claimFacts = productClaimFactsForAnchor(anchor);
  const comparisons = claimFacts.flatMap((fact) => productComparisonsForClaimFact(fact.claim_fact_id));
  if (factContext.extraction_status === "NEEDS_PRODUCT_SELECTION") {
    return `
      <div class="empty-state product-selection-cta">
        상품을 선택하지 않아 금리/우대조건/예금자보호 문구의 사실 대조가 완료되지 않았습니다.
      </div>
      ${productSelectionNotice(factContext)}
    `;
  }
  if (!claimFacts.length) {
    return `<div class="empty-state">이 문구에서 상품문서와 대조할 ClaimFact가 아직 추출되지 않았습니다.</div>`;
  }
  return `
    <div class="comparison-stack">
      ${claimFacts.map((fact) => {
        const rows = productComparisonsForClaimFact(fact.claim_fact_id);
        return `
          <article class="fact-card">
            <div class="card-top">
              <strong>${escapeHtml(fact.fact_type || "ClaimFact")} · ${escapeHtml(fact.value || "")}</strong>
              <span class="tag">${escapeHtml(fact.qualifier || "qualifier 없음")}</span>
            </div>
            <p class="evidence-text">${escapeHtml(fact.evidence_text || "-")}</p>
            ${rows.length ? rows.map(comparisonCard).join("") : `<div class="empty-state">비교 결과 없음</div>`}
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function renderProductFacts() {
  const context = state.result?.product_fact_context || {};
  const claimFacts = context.claim_facts || [];
  const productFacts = context.product_facts || [];
  const comparisons = context.comparison_results || [];
  const documents = context.selected_documents || [];
  const summary = productFactSummary(context);
  const prominenceDiagnostics = state.result?.prominence_diagnostics || [];
  if (!state.result) {
    els.productFactsTab.innerHTML = `<div class="empty-state">Review를 실행하면 상품문서 fact 대조가 여기에 표시됩니다.</div>`;
    return;
  }
  els.productFactsTab.innerHTML = `
    <section class="product-facts-header">
      <div>
        <h3>Product Fact Graph</h3>
        <p class="evidence-text">광고 ClaimFact와 상품문서 ProductFact를 대조해 조건 누락, 충돌, 근거 부재를 분리합니다.</p>
      </div>
      <div class="meta-row">
        <span class="badge ${productFactStatusClass(context.extraction_status)}">${escapeHtml(context.extraction_status || "NOT_RUN")}</span>
        <span class="tag">상품 ${escapeHtml(context.matched_product || "선택 필요")}</span>
        <span class="tag">문서 ${documents.length}</span>
        <span class="tag">ProductFact ${productFacts.length}</span>
        <span class="tag">ClaimFact ${claimFacts.length}</span>
        <span class="tag">현저성 ${prominenceDiagnostics.length}</span>
      </div>
    </section>
    ${productSelectionNotice(context)}
    ${context.reason ? `<div class="notice-box">${escapeHtml(context.reason)}</div>` : ""}
    <section class="product-facts-grid">
      <article class="fact-column">
        <h3>광고 ClaimFact</h3>
        ${claimFacts.length ? claimFacts.map(claimFactCard).join("") : `<div class="empty-state">상품을 선택하지 않아 금리/우대조건/예금자보호 문구의 사실 대조가 완료되지 않았습니다.</div>`}
      </article>
      <article class="fact-column">
        <h3>상품문서 ProductFact</h3>
        ${productFacts.length ? productFacts.map(productFactCard).join("") : `<div class="empty-state">선택 상품 PDF에서 ProductFact가 추출되지 않았습니다. 상품 선택 또는 문서 경로를 확인하세요.</div>`}
      </article>
      <article class="fact-column">
        <h3>비교 결과</h3>
        <div class="tag-row">${Object.entries(summary).map(([status, count]) => `<span class="tag ${productFactStatusClass(status)}">${escapeHtml(status)} ${escapeHtml(count)}</span>`).join("") || ""}</div>
        ${comparisons.length ? comparisons.map(comparisonCard).join("") : `<div class="empty-state">비교 결과가 없습니다.</div>`}
      </article>
    </section>
    <section class="detail-card">
      <h3>고지 현저성 진단</h3>
      <div class="evidence-text">
        ${prominenceDiagnostics.length ? prominenceDiagnostics.map((item) => `<b>${escapeHtml(item.diagnostic_code)}</b> · ${escapeHtml(item.severity || "")}<br />${escapeHtml(item.message || "")}<br />${escapeHtml(item.evidence || "")}`).join("<hr />") : "혜택 문구 대비 고지 위계 부족 신호가 없습니다."}
      </div>
    </section>
    <section class="detail-card">
      <h3>선택 문서</h3>
      <div class="evidence-text">
        ${documents.map((doc) => `<b>${escapeHtml(doc.label || "문서")}</b> · ${escapeHtml(doc.file_name || doc.original_name || doc.document_id)}<br />${escapeHtml(doc.relative_path || "")}<br />exists ${escapeHtml(doc.exists)}`).join("<hr />") || "상품명이 확정되지 않아 문서를 선택하지 않았습니다."}
      </div>
    </section>
  `;
}

function productSelectionNotice(context) {
  if (context.extraction_status !== "NEEDS_PRODUCT_SELECTION") return "";
  const candidates = state.result?.product_context?.matched_products || [];
  return `
    <section class="detail-card product-selection-cta">
      <h3>상품 선택 필요</h3>
      <p class="evidence-text">상품을 선택하지 않아 금리/우대조건/예금자보호 문구의 사실 대조가 완료되지 않았습니다. 광고 claim과 실제 상품문서 fact를 대조하려면 리뷰 대상 상품을 먼저 확정해야 합니다.</p>
      <div class="tag-row">
        ${candidates.slice(0, 8).map((item) => `<span class="tag">${escapeHtml(item.product || item.name || "상품 후보")}</span>`).join("") || `<span class="tag">상품 후보 없음</span>`}
      </div>
    </section>
  `;
}

function claimFactCard(item) {
  return `
    <article class="fact-card">
      <strong>${escapeHtml(item.fact_type || "fact")}</strong>
      <div class="meta-row">
        <span class="tag">${escapeHtml(item.value || "-")}</span>
        <span class="tag">${escapeHtml(item.qualifier || "qualifier 없음")}</span>
        <span class="tag">${escapeHtml(item.prominence_tier || "unknown")}</span>
        <span class="tag">${escapeHtml(item.claim_id || "")}</span>
      </div>
      <p class="evidence-text">${escapeHtml(item.evidence_text || "-")}</p>
    </article>
  `;
}

function productFactCard(item) {
  return `
    <article class="fact-card">
      <strong>${escapeHtml(item.fact_type || "fact")}</strong>
      <div class="meta-row">
        <span class="tag">${escapeHtml(item.value || "-")}</span>
        <span class="tag">${escapeHtml(item.unit || "")}</span>
        <span class="tag">${escapeHtml(item.condition || "조건 없음")}</span>
      </div>
      <p class="evidence-text">${escapeHtml(item.evidence_text || "-")}</p>
      <div class="meta-row">
        <span class="tag">${escapeHtml(item.source_document_id || "")}</span>
        <span class="tag">${escapeHtml(item.page_or_chunk || "")}</span>
      </div>
    </article>
  `;
}

function comparisonCard(item) {
  const claimFact = claimFactById(item.claim_fact_id);
  const productFact = productFactById(item.product_fact_id);
  return `
    <article class="fact-card comparison ${productFactStatusClass(item.status)}">
      <div class="card-top">
        <strong>${escapeHtml(item.status || "NO_PRODUCT_FACT")}</strong>
        <span class="tag">${Number(item.confidence || 0).toFixed(2)}</span>
      </div>
      <p class="evidence-text">
        <b>Claim</b><br />${escapeHtml(claimFact?.evidence_text || item.claim_fact_id || "-")}<br /><br />
        <b>ProductFact</b><br />${escapeHtml(productFact ? `${productFact.fact_type}: ${productFact.value} ${productFact.condition}` : "대응 fact 없음")}<br /><br />
        <b>판단</b><br />${escapeHtml(item.rationale || "-")}<br /><br />
        <b>근거</b><br />${escapeHtml(item.evidence_text || "-")}
      </p>
    </article>
  `;
}

function renderGraph() {
  const anchor = state.result?.context_anchors?.find((item) => item.anchor_id === state.selectedAnchorId);
  if (!anchor) {
    els.graphCanvas.innerHTML = `<div class="empty-state">선택된 경로가 없습니다.</div>`;
    return;
  }
  const claim = claimById(anchor.claim_id);
  const sentence = claim ? sentenceById(claim.sentence_id) : null;
  const claimFacts = productClaimFactsForAnchor(anchor).slice(0, 2);
  const comparisons = claimFacts.flatMap((fact) => productComparisonsForClaimFact(fact.claim_fact_id)).slice(0, 2);
  const prominenceDiagnostics = prominenceDiagnosticsForAnchor(anchor);
  const plans = state.result.cu_plan.filter((item) => item.anchor_id === anchor.anchor_id).slice(0, 2);
  const legalChains = chainsForAnchor(state.result?.policy_evidence_chains?.legal_basis_chains || [], anchor.anchor_id).filter((item) => item.status === "FOUND");
  const revision = revisionSuggestion(anchor.anchor_id);
  const steps = [
    evidenceStep("Claim", anchor.span.text, "심사 대상 문구"),
    evidenceStep("Qualifier / ClaimFact", qualifierAndFactText(anchor, claimFacts), "문제 표현과 fact-like 주장"),
    evidenceStep("ProductFact / Disclosure", productComparisonText(comparisons), "상품문서 사실 또는 필수고지 상태"),
    evidenceStep("Prominence", prominenceText(prominenceDiagnostics, claim), "고지 존재와 표시 위계"),
    evidenceStep("ConsumerEffect", claim?.consumer_effect || state.result?.overall_impression_judgment?.representative_consumer_impression || "소비자 영향 미상", "대표 소비자 인상"),
    evidenceStep("CU", plans.map((item) => item.risk_title || item.subject || item.principle).filter(Boolean).join("\n") || "CUPlan 없음", "정책 판단 단위"),
    evidenceStep("LegalBasis", legalChains.flatMap((chain) => chain.basis_nodes || []).map(chainNodeLabel).join("\n") || plans.map((item) => item.source_article).filter(Boolean).join("\n") || "법적 근거 미연결", "금소법/감독규정/심의기준"),
    evidenceStep("Revision", revision?.after || safeAlternative(anchor.span.text), "수정 또는 유지 조치"),
  ];
  els.graphCanvas.innerHTML = `
    <section class="evidence-path-header">
      <span class="tag">선택 Claim</span>
      <strong>${escapeHtml(anchor.span.text)}</strong>
      ${sentence ? `<span class="tag">${escapeHtml(sentence.role || "sentence")}</span>` : ""}
    </section>
    <section class="evidence-path-row">
      ${steps.map(evidenceStepCard).join("")}
    </section>
  `;
}

function evidenceStep(label, text, caption) {
  return { label, text: text || "-", caption };
}

function evidenceStepCard(step, index) {
  return `
    <article class="evidence-step-card">
      <div class="step-index">${index + 1}</div>
      <strong>${escapeHtml(step.label)}</strong>
      <p>${escapeHtml(shorten(step.text, 180))}</p>
      <span>${escapeHtml(step.caption)}</span>
    </article>
  `;
}

function qualifierAndFactText(anchor, claimFacts) {
  const qualifiers = claimQualifiers(anchor.claim_id).map((item) => item.text);
  const facts = claimFacts.map((item) => `${item.fact_type}: ${item.value} ${item.qualifier || ""}`.trim());
  return [...qualifiers, ...facts].filter(Boolean).join("\n") || anchor.hypernyms.map((item) => item.hypernym).join("\n");
}

function productComparisonText(comparisons) {
  if (state.result?.product_fact_context?.extraction_status === "NEEDS_PRODUCT_SELECTION") {
    return "상품을 선택하지 않아 금리/우대조건/예금자보호 문구의 사실 대조가 완료되지 않았습니다.";
  }
  return comparisons
    .map((item) => `${item.status}: ${item.rationale || item.evidence_text || ""}`.trim())
    .join("\n") || "대응 ProductFact/Disclosure 비교 결과 없음";
}

function prominenceText(diagnostics, claim) {
  if (!diagnostics.length) {
    return claim?.sentence_id ? "선택 문구 기준 현저성 부족 신호 없음" : "문장 위계 정보 없음";
  }
  return diagnostics.map((item) => `${item.diagnostic_code}: ${item.message || item.evidence || ""}`).join("\n");
}

function drawEdge(from, to, label) {
  if (!from || !to) return;
  const x1 = from.x + 150;
  const y1 = from.y + 34;
  const x2 = to.x;
  const y2 = to.y + 34;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const length = Math.sqrt(dx * dx + dy * dy);
  const angle = Math.atan2(dy, dx) * (180 / Math.PI);
  const edge = document.createElement("div");
  edge.className = "graph-edge";
  edge.style.left = `${x1}px`;
  edge.style.top = `${y1}px`;
  edge.style.width = `${length}px`;
  edge.style.transform = `rotate(${angle}deg)`;
  els.graphCanvas.appendChild(edge);
  const edgeLabel = document.createElement("div");
  edgeLabel.className = "graph-edge-label";
  edgeLabel.style.left = `${x1 + dx / 2 - 30}px`;
  edgeLabel.style.top = `${y1 + dy / 2 - 14}px`;
  edgeLabel.textContent = label;
  els.graphCanvas.appendChild(edgeLabel);
}

function renderAudit(steps) {
  const renderedSteps = steps.length ? steps : [];
  els.auditTrace.innerHTML = renderedSteps
    .map(
      (step) => `
      <article class="audit-step ${streamEventClass(step)}">
        <div class="card-top">
          <strong>${escapeHtml(step.name || step.step)}</strong>
          <span class="${auditBadgeClass(step)} badge">${auditBadgeText(step)}</span>
        </div>
        <p class="evidence-text">${escapeHtml(step.summary || "")}</p>
        ${step.counts ? `<div class="tag-row">${Object.entries(step.counts).map(([key, value]) => `<span class="tag">${escapeHtml(key)} ${escapeHtml(value)}</span>`).join("")}</div>` : ""}
        ${step.sample ? `<details><summary>sample</summary><div class="evidence-text">${escapeHtml(JSON.stringify(step.sample, null, 2))}</div></details>` : ""}
        ${step.payload ? `<details><summary>payload</summary><div class="evidence-text">${escapeHtml(JSON.stringify(step.payload, null, 2))}</div></details>` : ""}
        ${step.detail ? `<details open><summary>error detail</summary><div class="evidence-text">${escapeHtml(JSON.stringify(step.detail, null, 2))}</div></details>` : ""}
        ${step.received_at ? `<div class="audit-time">${escapeHtml(step.received_at)}</div>` : ""}
      </article>
    `
    )
    .join("") || `<div class="empty-state">Review를 실행하면 단계별 trace가 여기에 실시간으로 표시됩니다.</div>`;
}

function renderStreamingAudit() {
  renderAudit(state.streamEvents);
  if (!state.result && state.isStreaming) {
    els.verdictHeader.innerHTML = `<div class="verdict-main"><span class="verdict-label"><span class="badge review">실행 중</span></span><p class="verdict-desc">LLM/Neo4j 단계별 이벤트를 수신하고 있습니다.</p></div>${metricCell("Events", state.streamEvents.length)}${metricCell("Step", state.streamEvents.at(-1)?.step || "-")}${metricCell("Status", state.streamEvents.at(-1)?.event || "start")}${metricCell("Run", state.streamEvents.at(-1)?.review_run_id ? "생성됨" : "-")}`;
  }
}

function streamEventClass(step) {
  if (step.event === "error") return "is-error";
  if (step.event === "step_started") return "is-running";
  if (step.event === "result") return "is-result";
  return "";
}

function auditBadgeClass(step) {
  if (step.event === "error") return "badge reject";
  if (step.event === "step_started") return "badge review";
  if (step.event === "result" || step.event === "step_completed" || step.ok) return "badge pass";
  return "badge review";
}

function auditBadgeText(step) {
  if (step.event === "step_started") return "running";
  if (step.event === "step_completed") return "done";
  if (step.event === "result") return "result";
  if (step.event === "error") return "error";
  return step.ok ? "success" : "check";
}

function buildAuditSteps() {
  const result = state.result || {};
  const chains = result.policy_evidence_chains || {};
  const chainCount = (rows) => (rows || []).filter((row) => row.status === "FOUND").length;
  return [
    { name: "Context extraction", ok: (result.context_anchors || []).length > 0, summary: `${result.context_anchors?.length || 0} anchors generated` },
    { name: "Policy normalization", ok: allAnchorsHaveHypernyms(result), summary: "Approved PolicyHypernym vocabulary selected" },
    { name: "Anchor generation", ok: (result.context_anchors || []).length > 0, summary: "Anchor spans persisted under review run" },
    { name: "CU retrieval", ok: (result.cu_plan || []).length > 0, summary: `${result.cu_plan?.length || 0} CUPlan items · ${(result.system_review_items || []).length} diagnostics` },
    { name: "Policy evidence chains", ok: chainCount(chains.legal_basis_chains) > 0, summary: `${chainCount(chains.legal_basis_chains)} legal · ${chainCount(chains.disclosure_chains)} disclosure · ${chainCount(chains.exception_chains)} exception · ${(chains.chain_diagnostics || []).length} diagnostics` },
    { name: "LLM rerank", ok: (result.cu_plan || []).length > 0, summary: "Top candidates selected for judgment" },
    { name: "LLM judgment", ok: (result.judgments || []).length > 0, summary: `${result.judgments?.length || 0} judgments` },
    { name: "Exception override", ok: true, summary: `${result.exception_reviews?.length || 0} exception reviews` },
    { name: "Track B overall impression", ok: Boolean(result.overall_impression_judgment?.verdict), summary: `${result.overall_impression_judgment?.verdict || "pending"} · ${Number(result.overall_impression_judgment?.misleading_risk_score || 0).toFixed(2)}` },
    { name: "Product disclosure context", ok: Boolean(result.product_context?.product_group), summary: `${result.product_context?.product_group || "auto"} · ${(result.disclosure_requirements || []).length} required disclosures` },
    { name: "Product fact graph", ok: Boolean(result.product_fact_context?.extraction_status), summary: `${result.product_fact_context?.extraction_status || "pending"} · ${(result.product_fact_context?.comparison_results || []).length} comparisons` },
    { name: "Track C extension slot", ok: true, summary: result.track_c_summary?.status || "extension_ready" },
    { name: "Routing", ok: result.final_verdict !== "pass_candidate" || (result.cu_plan || []).length > 0, summary: result.final_verdict || "pending" },
  ];
}

function selectAnchor(anchorId) {
  state.selectedAnchorId = anchorId;
  renderResult();
}

function defaultAnchorId(result) {
  const anchors = result.context_anchors || [];
  const ranked = anchors
    .map((anchor) => ({ anchor, display: (result.anchor_display || []).find((item) => item.anchor_id === anchor.anchor_id) }))
    .sort((a, b) => verdictRank(b.display?.display_verdict || "ANCHOR") - verdictRank(a.display?.display_verdict || "ANCHOR"));
  return ranked[0]?.anchor.anchor_id || anchors[0]?.anchor_id || "";
}

function activateTab(tab) {
  document.querySelectorAll(".tab-button").forEach((button) => button.classList.toggle("is-active", button.dataset.tab === tab));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("is-active"));
  document.getElementById(`${tab}Tab`).classList.add("is-active");
}

function filteredAnchors() {
  const anchors = state.result?.context_anchors || [];
  if (!state.selectedPrinciple) return anchors;
  const principle = PRINCIPLES.find((item) => item.key === state.selectedPrinciple);
  return anchors.filter((anchor) => {
    const texts = [
      anchor.span.text,
      ...anchor.hypernyms.map((item) => item.hypernym),
      ...state.result.cu_plan.filter((plan) => plan.anchor_id === anchor.anchor_id).map((plan) => `${plan.principle} ${plan.subject} ${plan.constraint}`),
    ].join(" ");
    return principle.match.some((token) => texts.includes(token));
  });
}

function judgmentsForAnchor(anchorId) {
  const planIds = state.result.cu_plan.filter((item) => item.anchor_id === anchorId).map((item) => item.plan_item_id);
  return state.result.judgments.filter((item) => planIds.includes(item.plan_item_id));
}

function effectiveJudgmentsForAnchor(anchorId) {
  const planIds = state.result.cu_plan.filter((item) => item.anchor_id === anchorId).map((item) => item.plan_item_id);
  return (state.result.effective_judgments || state.result.judgments).filter((item) => planIds.includes(item.plan_item_id));
}

function rawJudgment(judgmentId) {
  return (state.result.judgments || []).find((item) => item.judgment_id === judgmentId);
}

function primaryJudgment(anchorId) {
  const judgments = effectiveJudgmentsForAnchor(anchorId);
  return judgments.sort((a, b) => verdictRank(b.verdict) - verdictRank(a.verdict) || Number(b.score || 0) - Number(a.score || 0))[0] || null;
}

function primaryJudgmentFromResult(result, anchorId) {
  const planIds = (result.cu_plan || []).filter((item) => item.anchor_id === anchorId).map((item) => item.plan_item_id);
  return (result.effective_judgments || result.judgments || [])
    .filter((item) => planIds.includes(item.plan_item_id))
    .sort((a, b) => verdictRank(b.verdict) - verdictRank(a.verdict) || Number(b.score || 0) - Number(a.score || 0))[0] || null;
}

function alignSpan(sourceText, span) {
  const fallback = { start: span.start, end: span.end };
  if (!span?.text) return fallback;
  if (Number.isInteger(span.start) && Number.isInteger(span.end) && sourceText.slice(span.start, span.end) === span.text) {
    return fallback;
  }
  const exactIndex = sourceText.indexOf(span.text);
  if (exactIndex >= 0) return { start: exactIndex, end: exactIndex + span.text.length };
  const compactNeedle = span.text.replace(/\s+/g, " ").trim();
  const compactIndex = sourceText.indexOf(compactNeedle);
  if (compactIndex >= 0) return { start: compactIndex, end: compactIndex + compactNeedle.length };
  return fallback;
}

function aggregateVerdict(judgments) {
  if (!judgments.length) return "ANCHOR";
  return judgments.sort((a, b) => verdictRank(b.verdict) - verdictRank(a.verdict) || Number(b.score || 0) - Number(a.score || 0))[0].verdict;
}

function verdictRank(verdict) {
  return { NON_COMPLIANT: 5, RETRIEVAL_FAILURE: 4, INSUFFICIENT: 3, COMPLIANT: 2, NOT_APPLICABLE: 1, ANCHOR: 0 }[verdict] || 0;
}

function highlightClass(judgment) {
  const verdict = typeof judgment === "string" ? judgment : judgment?.verdict;
  if (!verdict) return "anchor-only";
  if (verdict === "NON_COMPLIANT") return "non-compliant";
  if (verdict === "INSUFFICIENT" || verdict === "RETRIEVAL_FAILURE") return "insufficient";
  if (verdict === "COMPLIANT" || verdict === "NOT_APPLICABLE") return "compliant";
  if (verdict === "SCOPE") return "anchor-only";
  return "anchor-only";
}

function principleStatuses(result) {
  const statuses = {};
  const actionableSystemItems = systemReviewItems(result).filter((item) => isActionableAnchor(item.anchor_id));
  if ((result.context_anchors || []).length && !(result.cu_plan || []).length && actionableSystemItems.length) {
    PRINCIPLES.forEach((principle) => {
      statuses[principle.key] = "검토 필요";
    });
    return statuses;
  }
  PRINCIPLES.forEach((principle) => {
    const related = (result.cu_plan || []).filter((item) =>
      principle.match.some((token) => `${item.principle} ${item.subject} ${item.constraint} ${item.context}`.includes(token))
    );
    const unmatched = unmatchedAnchors(result).filter((anchor) =>
      isActionableAnchor(anchor.anchor_id) &&
      principle.match.some((token) => `${anchor.span.text} ${anchor.hypernyms?.map((item) => item.hypernym).join(" ")}`.includes(token))
    );
    if (!related.length) {
      statuses[principle.key] = unmatched.length ? "검토 필요" : "해당 없음";
      return;
    }
    const judgments = (result.effective_judgments || result.judgments).filter((judgment) => {
      const anchorDisplayRow = anchorDisplay(judgment.anchor_id, result);
      return anchorDisplayRow?.display_role !== "scope" && related.some((item) => item.plan_item_id === judgment.plan_item_id);
    });
    if (judgments.some((item) => item.verdict === "NON_COMPLIANT" && Number(item.score || 0) >= 0.82)) statuses[principle.key] = "위반 가능성";
    else if (judgments.some((item) => item.verdict === "NON_COMPLIANT")) statuses[principle.key] = "수정 필요";
    else if (judgments.some((item) => item.verdict === "INSUFFICIENT")) statuses[principle.key] = "검토 필요";
    else if (unmatched.length) statuses[principle.key] = "검토 필요";
    else statuses[principle.key] = "문제 없음";
  });
  return statuses;
}

function conditionalDisclosures(result) {
  const text = els.text.value;
  const signals = [];
  if (/예금자보호|1억원|보호됩니다/.test(text)) signals.push("예금자보호 한도 고지");
  if (/우대조건|가입기간|달라질 수|조건 충족/.test(text)) signals.push("금리/우대조건 고지");
  if (/원금손실|손실 가능성|투자위험/.test(text)) signals.push("원금손실/투자위험 고지");
  if (/과거.*미래|미래.*보장하지/.test(text)) signals.push("과거성과 미래보장 아님 고지");
  if (result.final_verdict === "pass_candidate" && signals.length) return signals;
  return signals.filter((signal) => /고지/.test(signal));
}

function disclosureSignals(anchor) {
  const text = `${anchor.span.text} ${anchor.facts.join(" ")} ${anchor.hypernyms.map((item) => item.hypernym).join(" ")}`;
  const signals = [];
  if (/예금자보호|1억원|보호/.test(text)) signals.push("예금자보호 고지 있음");
  if (/우대조건|가입기간|조건/.test(text)) signals.push("조건/우대금리 고지 있음");
  if (/원금손실|투자위험/.test(text)) signals.push("위험 고지 있음");
  if (!signals.length && /보장|확정|수익/.test(text)) signals.push("완화 고지 확인 필요");
  return signals;
}

function safeAlternative(text) {
  if (/고수익|보장|확정|조건 없이/.test(text)) {
    return "우대조건 충족 시 최고 금리가 적용될 수 있으며, 적용 조건과 제한사항은 상품설명서 및 약관을 확인하시기 바랍니다.";
  }
  if (/조기상환|성과|수익률/.test(text)) {
    return "과거 성과는 참고자료이며 미래 수익 또는 상환 가능성을 보장하지 않습니다. 상품 구조와 손실 가능성을 확인하시기 바랍니다.";
  }
  return "상품의 적용 조건, 위험, 수수료 및 필수고지를 함께 표시하는 문안으로 수정하시기 바랍니다.";
}

function maxSeverity(result) {
  return Math.max(0, ...(result.detected_issues || []).map((item) => Number(item.severity || 0)));
}

function verdictClass(verdict) {
  return { pass_candidate: "pass", needs_review: "review", revise: "revise", reject: "reject" }[verdict] || "review";
}

function judgmentBadgeClass(verdict) {
  return { NON_COMPLIANT: "reject", RETRIEVAL_FAILURE: "review", INSUFFICIENT: "review", COMPLIANT: "pass", NOT_APPLICABLE: "pass", SCOPE: "pass", ANCHOR: "review" }[verdict] || "review";
}

function graphStatusClass(status) {
  return {
    NON_COMPLIANT: "graph-bad",
    INSUFFICIENT: "graph-review",
    COMPLIANT: "graph-pass",
    NOT_APPLICABLE: "graph-pass",
    review: "graph-review",
    plan: "graph-plan",
    evidence: "graph-evidence",
    exception: "graph-exception",
  }[status] || "";
}

function trackBBadgeClass(trackB) {
  const score = Number(trackB?.misleading_risk_score || 0);
  if (trackB?.verdict === "HIGH" || score >= 0.75) return "reject";
  if (trackB?.verdict === "MEDIUM" || score >= 0.45) return "review";
  return "pass";
}

function trackBGraphStatus() {
  const trackB = state.result?.overall_impression_judgment || {};
  const score = Number(trackB.misleading_risk_score || 0);
  if (trackB.verdict === "HIGH" || score >= 0.75) return "NON_COMPLIANT";
  if (trackB.verdict === "MEDIUM" || score >= 0.45) return "review";
  return "COMPLIANT";
}

function statusClass(status) {
  if (status === "위반 가능성") return "status-bad";
  if (status === "수정 필요") return "status-revise";
  if (status === "검토 필요") return "status-review";
  if (status === "문제 없음") return "status-ok";
  return "";
}

function allAnchorsHaveHypernyms(result) {
  return (result.context_anchors || []).every((anchor) => anchor.hypernyms?.length);
}

function anchorPlanCount(anchorId) {
  return (state.result?.cu_plan || []).filter((item) => item.anchor_id === anchorId).length;
}

function anchorDisplay(anchorId, result = state.result) {
  return (result?.anchor_display || []).find((item) => item.anchor_id === anchorId);
}

function isActionableAnchor(anchorId, result = state.result) {
  return anchorDisplay(anchorId, result)?.display_role === "actionable";
}

function systemReviewItems(result = state.result) {
  return result?.system_review_items || [];
}

function revisionSuggestion(anchorId) {
  return (state.result?.revision_suggestions || []).find((item) => item.anchor_id === anchorId);
}

function productFactSummary(context = state.result?.product_fact_context || {}) {
  const summary = {};
  (context.comparison_results || []).forEach((item) => {
    const status = item.status || "UNKNOWN";
    summary[status] = (summary[status] || 0) + 1;
  });
  return summary;
}

function productClaimFactsForAnchor(anchor) {
  return (state.result?.product_fact_context?.claim_facts || []).filter((item) => item.claim_id === anchor.claim_id);
}

function claimQualifiers(claimId) {
  return (state.result?.claims || []).find((item) => item.claim_id === claimId)?.qualifiers || [];
}

function claimById(claimId) {
  return (state.result?.claims || []).find((item) => item.claim_id === claimId);
}

function sentenceById(sentenceId) {
  return (state.result?.sentence_units || []).find((item) => item.sentence_id === sentenceId);
}

function claimsForSentence(sentenceId) {
  return (state.result?.claims || []).filter((item) => item.sentence_id === sentenceId);
}

function anchorForClaim(claimId) {
  return (state.result?.context_anchors || []).find((item) => item.claim_id === claimId);
}

function anchorForSentence(sentenceId) {
  const claim = claimsForSentence(sentenceId)[0];
  return claim ? anchorForClaim(claim.claim_id) : null;
}

function policyBasisForAnchor(anchor) {
  const planIds = (state.result?.cu_plan || [])
    .filter((item) => item.anchor_id === anchor.anchor_id)
    .map((item) => item.plan_item_id);
  return (state.result?.cu_plan || [])
    .filter((item) => planIds.includes(item.plan_item_id))
    .map((item) => item.source_article || item.principle || item.subject)
    .filter(Boolean);
}

function productComparisonsForClaimFact(claimFactId) {
  return (state.result?.product_fact_context?.comparison_results || []).filter((item) => item.claim_fact_id === claimFactId);
}

function prominenceDiagnosticsForAnchor(anchor) {
  const claim = claimById(anchor.claim_id);
  const sentenceId = claim?.sentence_id || "";
  return (state.result?.prominence_diagnostics || []).filter((item) => item.benefit_sentence_id === sentenceId || item.evidence?.includes(anchor.span.text));
}

function claimFactById(claimFactId) {
  return (state.result?.product_fact_context?.claim_facts || []).find((item) => item.claim_fact_id === claimFactId);
}

function productFactById(productFactId) {
  return (state.result?.product_fact_context?.product_facts || []).find((item) => item.fact_id === productFactId);
}

function productFactStatusClass(status) {
  if (status === "SUPPORTED" || status === "EXTRACTED") return "pass";
  if (status === "CONTRADICTED" || status === "FACT_EXTRACTION_FAILED" || status === "TEXT_EXTRACTION_FAILED") return "reject";
  if (status === "PROMINENCE_INSUFFICIENT" || status === "CONDITION_MISSING") return "review";
  return "review";
}

function comparisonStatusForGraph(status) {
  if (status === "SUPPORTED") return "COMPLIANT";
  if (status === "CONTRADICTED") return "NON_COMPLIANT";
  return "review";
}

function unmatchedAnchors(result) {
  return (result.context_anchors || []).filter(
    (anchor) => !(result.cu_plan || []).some((plan) => plan.anchor_id === anchor.anchor_id)
  );
}

function shorten(text, max) {
  const value = String(text || "");
  return value.length > max ? `${value.slice(0, max)}...` : value;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function copyRunId() {
  if (!state.result?.review_run_id) return;
  await navigator.clipboard.writeText(state.result.review_run_id);
}

init();
