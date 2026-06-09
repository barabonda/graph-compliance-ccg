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

const EXAMPLES = [
  {
    label: "예금 · 고지 있음",
    product: "deposit",
    channel: "web_page",
    title: "JB시니어우대예금 특판",
    text:
      "JB시니어우대예금 특판 안내. 최고 연 5.0% 금리를 확정 제공하며 안정적으로 목돈을 관리할 수 있습니다. 기본금리와 우대금리는 가입기간, 우대조건 충족 여부에 따라 달라질 수 있습니다. 이 예금은 예금자보호법에 따라 원금과 이자를 합하여 1인당 최고 5천만원까지 보호됩니다.",
  },
  {
    label: "예금 · 보장 위험",
    product: "deposit",
    channel: "web_page",
    title: "고지 없는 특판예금",
    text:
      "JB 특판예금 출시. 누구나 연 5% 확정 보장 수익을 받을 수 있는 절호의 기회입니다. 지금 가입하면 조건 없이 안정적인 고수익을 보장합니다.",
  },
  {
    label: "투자 · ELS",
    product: "investment",
    channel: "web_page",
    title: "ELS 광고 초안",
    text:
      "요즘 같은 변동성 장세에서는 ELS를 이해하는 것이 중요합니다. OO증권의 더블찬스 ELS는 안정성과 수익성을 동시에 고려한 상품입니다. 지난 3년간 유사 구조 상품의 조기상환 성공률이 높았기 때문에, 중위험 투자자에게 좋은 선택이 될 수 있습니다.",
  },
];

const state = {
  result: null,
  selectedAnchorId: "",
  selectedPrinciple: "",
};

const els = {
  form: document.getElementById("reviewForm"),
  title: document.getElementById("titleInput"),
  product: document.getElementById("productInput"),
  channel: document.getElementById("channelInput"),
  text: document.getElementById("textInput"),
  examples: document.getElementById("examples"),
  button: document.getElementById("reviewButton"),
  error: document.getElementById("errorMessage"),
  verdictHeader: document.getElementById("verdictHeader"),
  riskStrip: document.getElementById("riskStrip"),
  highlightedText: document.getElementById("highlightedText"),
  conditionalNotice: document.getElementById("conditionalNotice"),
  detail: document.getElementById("detailContent"),
  runLabel: document.getElementById("reviewRunLabel"),
  copyRun: document.getElementById("copyRunButton"),
  claimsTab: document.getElementById("claimsTab"),
  graphCanvas: document.getElementById("graphCanvas"),
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
  els.text.value = example.text;
}

async function runReview(event) {
  event.preventDefault();
  els.error.hidden = true;
  els.button.disabled = true;
  els.button.textContent = "Reviewing...";
  const payload = {
    dataset_item_id: `console_${Date.now()}`,
    title: els.title.value,
    content_text: els.text.value,
    channel: els.channel.value,
    product_group: els.product.value,
    workspace_id: "graphcompliance_mvp_jb_20260530",
  };
  try {
    const response = await fetch("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(await formatApiError(response));
    }
    state.result = await response.json();
    els.error.textContent = "";
    els.error.hidden = true;
    state.selectedAnchorId = defaultAnchorId(state.result);
    state.selectedPrinciple = "";
    renderResult();
  } catch (error) {
    els.error.textContent = String(error.message || error);
    els.error.hidden = false;
  } finally {
    els.button.disabled = false;
    els.button.textContent = "Review";
  }
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
  els.conditionalNotice.textContent = "통과 후보도 완전 면책이 아니라 현재 문안 기준의 1차 검토 결과입니다.";
  els.detail.innerHTML = `<div class="empty-state">하이라이트나 Claim 카드를 선택하면 상세 판단이 표시됩니다.</div>`;
  els.claimsTab.innerHTML = "";
  els.graphCanvas.innerHTML = "";
  renderAudit([]);
}

function renderResult() {
  renderVerdictHeader();
  renderRiskStrip();
  renderHighlights();
  renderClaimCards();
  renderDetail();
  renderGraph();
  renderAudit(buildAuditSteps());
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
  const anchors = filteredAnchors();
  const spans = anchors
    .map((anchor) => {
      const display = anchorDisplay(anchor.anchor_id);
      const aligned = alignSpan(text, anchor.span);
      const className = highlightClass(display?.display_verdict || "ANCHOR");
      return {
        id: anchor.anchor_id,
        start: aligned.start,
        end: aligned.end,
        text: anchor.span.text,
        className,
      };
    })
    .filter((span) => Number.isInteger(span.start) && Number.isInteger(span.end))
    .sort((a, b) => a.start - b.start || b.end - a.end);

  let cursor = 0;
  const parts = [];
  spans.forEach((span) => {
    if (span.start < cursor || span.start < 0 || span.end > text.length || span.end <= span.start) return;
    parts.push(escapeHtml(text.slice(cursor, span.start)));
    parts.push(
      `<button class="hl ${span.className} ${state.selectedAnchorId === span.id ? "is-selected" : ""}" data-anchor-id="${span.id}" type="button">${escapeHtml(text.slice(span.start, span.end))}</button>`
    );
    cursor = span.end;
  });
  parts.push(escapeHtml(text.slice(cursor)));
  els.highlightedText.innerHTML = parts.join("") || `<div class="empty-state">광고 원문이 비어 있습니다.</div>`;
  els.highlightedText.querySelectorAll(".hl").forEach((button) => {
    button.addEventListener("click", () => selectAnchor(button.dataset.anchorId));
  });
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
        <span class="tag">${escapeHtml(anchor.anchor_type)}</span>
        <span class="tag">${display?.display_role === "scope" ? "scope/context" : "actionable"}</span>
        ${anchor.hypernyms.map((item) => `<span class="tag">${escapeHtml(item.hypernym)} · ${item.support}</span>`).join("")}
      </div>
      <details open>
        <summary>Context facts</summary>
        <div class="evidence-text">${anchor.facts.map(escapeHtml).join("<br />") || "없음"}</div>
      </details>
    </section>
    <section class="detail-card">
      <h3>CU별 판단</h3>
      ${
        effective.length
          ? effective.map((judgment) => judgmentCard(judgment, planItems.find((item) => item.plan_item_id === judgment.plan_item_id), rawJudgment(judgment.judgment_id))).join("")
          : planItems.length
            ? `<div class="empty-state">CUPlan은 생성됐지만 이 anchor에 대한 judgment가 없습니다. LLM judgment 단계를 확인하세요.</div>`
            : `<div class="empty-state">이 anchor에 매칭된 CU가 없습니다. 정책 매칭 실패로 검토 필요 상태입니다.</div>`
      }
    </section>
    <section class="detail-card">
      <h3>Track B · 소비자 오인</h3>
      ${overallImpressionPanel(anchor)}
    </section>
    <section class="detail-card">
      <h3>Product / Disclosure</h3>
      ${productDisclosurePanel(anchor)}
    </section>
    <section class="detail-card">
      <h3>예외/고지 검토</h3>
      ${exceptionPanel(anchor, exceptions)}
    </section>
    <section class="detail-card">
      <h3>수정 제안</h3>
      ${revisionPanel(anchor, issues, effective, display)}
    </section>
  `;
}

function judgmentCard(judgment, planItem, raw) {
  const evidence = planItem?.evidence_texts || [];
  const rawTag = raw && raw.verdict !== judgment.verdict ? `<span class="tag">raw ${escapeHtml(raw.verdict)}</span>` : "";
  return `
    <article class="judgment-card">
      <div class="card-top">
        <strong>${escapeHtml(planItem?.principle || "ComplianceUnit")}</strong>
        <span class="badge ${judgmentBadgeClass(judgment.verdict)}">${JUDGMENT_STATUS[judgment.verdict] || judgment.verdict}</span>
      </div>
      <div class="meta-row">
        <span class="tag">score ${Number(judgment.score || 0).toFixed(2)}</span>
        <span class="tag">${escapeHtml(judgment.cu_id)}</span>
        ${rawTag}
      </div>
      <p class="evidence-text">${escapeHtml(judgment.why)}</p>
      <details>
        <summary>근거 / Evidence window</summary>
        <div class="evidence-text">
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
  const after = safeAlternative(anchor.span.text);
  return `
    ${issues.map((issue) => `<article class="revision-card"><strong>${escapeHtml(issue.required_action || "문안 수정 필요")}</strong><p class="evidence-text">${escapeHtml(issue.rationale || "")}</p></article>`).join("")}
    <article class="revision-card">
      <strong>대체 문안 예시</strong>
      <p class="evidence-text"><b>Before</b><br />${escapeHtml(anchor.span.text)}<br /><br /><b>After</b><br />${escapeHtml(after)}</p>
    </article>
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

function productDisclosurePanel(anchor) {
  const context = state.result?.product_context || {};
  const requirements = state.result?.disclosure_requirements || [];
  const products = context.matched_products || [];
  return `
    <article class="judgment-card">
      <div class="meta-row">
        <span class="tag">상품군 ${escapeHtml(context.product_group || "auto")}</span>
        <span class="tag">상품 ${products.length}</span>
        <span class="tag">문서 ${Number(context.document_count || 0)}</span>
      </div>
      <details open>
        <summary>필요 고지 후보</summary>
        <div class="evidence-text">
          ${requirements.map((item) => `<b>${escapeHtml(item.label)}</b> · ${escapeHtml(item.source)}<br />${escapeHtml(item.why)}`).join("<hr />") || "-"}
        </div>
      </details>
      <details>
        <summary>ProductDocument grounding</summary>
        <div class="evidence-text">
          ${products.map((item) => `<b>${escapeHtml(item.product)}</b><br />${escapeHtml(item.major)} / ${escapeHtml(item.subcategory)} / ${escapeHtml(item.category)}<br />문서 ${Number(item.document_count || 0)} · ${(item.document_labels || []).map(escapeHtml).join(", ")}`).join("<hr />") || "광고 문안과 직접 매칭된 상품명은 없습니다. 상품군 기준 고지 후보만 사용합니다."}
        </div>
      </details>
      <p class="evidence-text">v1은 상품 메타데이터 기반 확인 문서와 고지 후보만 제시합니다. 실제 금리/수수료/우대조건 사실 대조는 PDF 본문 DisclosureFact 추출 후 v2에서 수행합니다.</p>
    </article>
  `;
}

function renderGraph() {
  const anchor = state.result?.context_anchors?.find((item) => item.anchor_id === state.selectedAnchorId);
  if (!anchor) {
    els.graphCanvas.innerHTML = `<div class="empty-state">선택된 경로가 없습니다.</div>`;
    return;
  }
  const planItems = state.result.cu_plan.filter((item) => item.anchor_id === anchor.anchor_id).slice(0, 5);
  const nodes = [
    { id: "claim", label: "Claim", text: anchor.span.text, x: 24, y: 150 },
    { id: "anchor", label: "ContextAnchor", text: anchor.anchor_type, x: 220, y: 150 },
    { id: "hypernym", label: "PolicyHypernym", text: anchor.hypernyms.map((item) => item.hypernym).join(", "), x: 430, y: 150 },
    { id: "trackb", label: "Track B", text: `${state.result?.overall_impression_judgment?.verdict || "overall impression"} · ${Number(state.result?.overall_impression_judgment?.misleading_risk_score || 0).toFixed(2)}`, x: 430, y: 300, status: trackBGraphStatus() },
    { id: "product", label: "Product", text: `${state.result?.product_context?.product_group || "auto"} · docs ${Number(state.result?.product_context?.document_count || 0)}`, x: 430, y: 20, status: "evidence" },
  ];
  const edges = [
    ["claim", "anchor", "HAS_ANCHOR"],
    ["anchor", "hypernym", "NORMALIZED_TO"],
    ["claim", "trackb", "MEANING_IMPLICATURE_EFFECT"],
    ["claim", "product", "ABOUT_PRODUCT_SCOPE"],
  ];
  if (!planItems.length) {
    const display = anchorDisplay(anchor.anchor_id);
    nodes.push({ id: "failure", label: "Retrieval", text: `CUPlan 0 · ${display?.retrieval_failure_code || "정책 매칭 실패"}`, x: 650, y: 150, status: "review" });
    edges.push(["hypernym", "failure", "NO_CU_MATCH"]);
  }
  planItems.forEach((plan, index) => {
    const y = 70 + index * 120;
    const judgment = state.result.judgments.find((item) => item.plan_item_id === plan.plan_item_id);
    const effective = state.result.effective_judgments?.find((item) => item.judgment_id === judgment?.judgment_id) || judgment;
    const exception = judgment
      ? state.result.exception_reviews.find((item) => item.judgment_id === judgment.judgment_id)
      : null;
    nodes.push(
      { id: `plan_${index}`, label: "CUPlanItem", text: `${plan.principle || "원칙 미상"} · ${plan.retrieval_basis || "basis"} · ${plan.gate_status || "gate"}`, x: 660, y, status: "plan" },
      { id: `cu_${index}`, label: "ComplianceUnit", text: `${plan.subject || plan.cu_id} ${plan.constraint || ""}`, x: 880, y, status: effective?.verdict || "review" },
      { id: `evidence_${index}`, label: "Premise / Legal", text: (plan.legal_evidence_ids || []).slice(0, 3).join(", ") || "evidence window", x: 660, y: y + 72, status: "evidence" },
      { id: `judgment_${index}`, label: "LLMJudgment", text: effective?.verdict || "not judged", x: 880, y: y + 72, status: effective?.verdict || "review" }
    );
    edges.push(
      ["hypernym", `plan_${index}`, "RETRIEVES"],
      [`plan_${index}`, `cu_${index}`, "TARGETS_CU"],
      [`plan_${index}`, `evidence_${index}`, "USES_EVIDENCE"],
      [`plan_${index}`, `judgment_${index}`, "JUDGED_AS"]
    );
    if (exception) {
      nodes.push({ id: `exception_${index}`, label: "ExceptionReview", text: `${exception.effect} · ${exception.applies ? "applied" : "not applied"}`, x: 1090, y: y + 72, status: "exception" });
      edges.push([`judgment_${index}`, `exception_${index}`, "HAS_EXCEPTION_REVIEW"]);
    }
  });
  els.graphCanvas.innerHTML = "";
  nodes.forEach((node) => {
    const div = document.createElement("div");
    div.className = `graph-node ${graphStatusClass(node.status)}`;
    div.style.left = `${node.x}px`;
    div.style.top = `${node.y}px`;
    div.innerHTML = `<strong>${escapeHtml(node.label)}</strong>${escapeHtml(shorten(node.text, 80))}`;
    els.graphCanvas.appendChild(div);
  });
  edges.forEach(([from, to, label]) => drawEdge(nodes.find((n) => n.id === from), nodes.find((n) => n.id === to), label));
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
  els.auditTrace.innerHTML = steps
    .map(
      (step) => `
      <article class="audit-step">
        <strong>${escapeHtml(step.name)}</strong>
        <span class="${step.ok ? "status-ok" : "status-review"} badge">${step.ok ? "success" : "check"}</span>
        <p class="evidence-text">${escapeHtml(step.summary)}</p>
      </article>
    `
    )
    .join("");
}

function buildAuditSteps() {
  const result = state.result || {};
  return [
    { name: "Context extraction", ok: (result.context_anchors || []).length > 0, summary: `${result.context_anchors?.length || 0} anchors generated` },
    { name: "Policy normalization", ok: allAnchorsHaveHypernyms(result), summary: "Approved PolicyHypernym vocabulary selected" },
    { name: "Anchor generation", ok: (result.context_anchors || []).length > 0, summary: "Anchor spans persisted under review run" },
    { name: "CU retrieval", ok: (result.cu_plan || []).length > 0, summary: `${result.cu_plan?.length || 0} CUPlan items · ${(result.system_review_items || []).length} diagnostics` },
    { name: "LLM rerank", ok: (result.cu_plan || []).length > 0, summary: "Top candidates selected for judgment" },
    { name: "LLM judgment", ok: (result.judgments || []).length > 0, summary: `${result.judgments?.length || 0} judgments` },
    { name: "Exception override", ok: true, summary: `${result.exception_reviews?.length || 0} exception reviews` },
    { name: "Track B overall impression", ok: Boolean(result.overall_impression_judgment?.verdict), summary: `${result.overall_impression_judgment?.verdict || "pending"} · ${Number(result.overall_impression_judgment?.misleading_risk_score || 0).toFixed(2)}` },
    { name: "Product disclosure context", ok: Boolean(result.product_context?.product_group), summary: `${result.product_context?.product_group || "auto"} · ${(result.disclosure_requirements || []).length} required disclosures` },
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
  if (/예금자보호|5천만원|보호됩니다/.test(text)) signals.push("예금자보호 한도 고지");
  if (/우대조건|가입기간|달라질 수|조건 충족/.test(text)) signals.push("금리/우대조건 고지");
  if (/원금손실|손실 가능성|투자위험/.test(text)) signals.push("원금손실/투자위험 고지");
  if (/과거.*미래|미래.*보장하지/.test(text)) signals.push("과거성과 미래보장 아님 고지");
  if (result.final_verdict === "pass_candidate" && signals.length) return signals;
  return signals.filter((signal) => /고지/.test(signal));
}

function disclosureSignals(anchor) {
  const text = `${anchor.span.text} ${anchor.facts.join(" ")} ${anchor.hypernyms.map((item) => item.hypernym).join(" ")}`;
  const signals = [];
  if (/예금자보호|5천만원|보호/.test(text)) signals.push("예금자보호 고지 있음");
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
