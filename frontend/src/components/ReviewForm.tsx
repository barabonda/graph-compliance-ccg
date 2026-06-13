"use client";

import { useState, type FormEvent } from "react";
import { getActor } from "@/lib/actor";
import { CHANNELS, EXAMPLES, LLM_MODELS, PRODUCT_GROUPS, WORKSPACE_ID, type ExamplePreset } from "@/lib/labels";
import type { ReviewRequest } from "@/lib/types";
import { Icon } from "./Icon";

interface Props {
  running: boolean;
  onSubmit: (payload: ReviewRequest) => void;
  onLoadSample?: () => void;
  onLoadProductSample?: () => void;
}

const DEFAULT_EXAMPLE = EXAMPLES[1];

/** 채널별 형식 요건 안내(심의기준 기반). */
const CHANNEL_FORMAT_HINT: Record<string, string> = {
  web_page: "심의필 번호·유효기간 표시, 위험고지 동일 지면 노출",
  bank_event_page_text: "심의필 번호·유효기간 표시, 위험고지 동일 지면 노출",
  push: "제한된 분량 — 핵심 위험고지 누락 주의, 상세는 연결 페이지로",
  sns: "추천·보증 시 경제적 이해관계 표시, 판매업자 명칭 노출",
  youtube: "음성·자막 위험고지 속도/노출, 직접판매업자 확인 표시",
};

/** 위험 성격 점 색 — 라벨로 추정(고지 포함=초록, 위험/ELS=빨강). */
function exampleDot(example: ExamplePreset): string {
  if (example.label.includes("고지")) return "var(--pass)";
  return "var(--reject)";
}

export function ReviewForm({ running, onSubmit, onLoadSample, onLoadProductSample }: Props) {
  const [title, setTitle] = useState(DEFAULT_EXAMPLE.title);
  const [productGroup, setProductGroup] = useState(DEFAULT_EXAMPLE.product);
  const [channel, setChannel] = useState(DEFAULT_EXAMPLE.channel);
  const [selectedProduct, setSelectedProduct] = useState(DEFAULT_EXAMPLE.selectedProduct);
  const [text, setText] = useState(DEFAULT_EXAMPLE.text);
  const [llmModel, setLlmModel] = useState("");

  const fillExample = (example: ExamplePreset) => {
    setTitle(example.title);
    setProductGroup(example.product);
    setChannel(example.channel);
    setSelectedProduct(example.selectedProduct);
    setText(example.text);
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!text.trim() || running) return;
    onSubmit({
      dataset_item_id: `console_${Date.now()}`,
      title,
      content_text: text,
      channel,
      product_group: productGroup,
      selected_product_name: selectedProduct.trim(),
      workspace_id: WORKSPACE_ID,
      llm_model: llmModel || undefined,
      actor: getActor(),
    });
  };

  const fieldClass =
    "w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand focus:ring-2 focus:ring-brand/20";
  const channelLabel = CHANNELS.find((item) => item.value === channel)?.label ?? channel;
  const formatHint = CHANNEL_FORMAT_HINT[channel] ?? "심의필 번호·유효기간 표시, 위험고지 명확 표시";
  const noProduct = !selectedProduct.trim();

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      {/* 샘플 프리셋 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-bold text-ink-4">샘플</span>
        {EXAMPLES.map((example) => (
          <button
            key={example.label}
            type="button"
            onClick={() => fillExample(example)}
            className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 text-xs font-semibold text-ink-2 hover:border-brand hover:text-brand"
          >
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: exampleDot(example) }} />
            {example.label}
          </button>
        ))}
        <span className="ml-auto flex gap-2">
          {onLoadSample && (
            <button type="button" onClick={onLoadSample} className="text-[11px] font-semibold text-ink-4 underline-offset-2 hover:text-brand hover:underline">
              저장 결과
            </button>
          )}
          {onLoadProductSample && (
            <button type="button" onClick={onLoadProductSample} className="text-[11px] font-semibold text-ink-4 underline-offset-2 hover:text-brand hover:underline">
              상품대조 샘플
            </button>
          )}
        </span>
      </div>

      <label className="block">
        <span className="mb-1 flex items-center gap-1.5 text-xs font-bold text-ink-3">
          심사 제목 <span className="font-normal text-ink-4">내부 식별용</span>
        </span>
        <input
          className={fieldClass}
          type="text"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="예: 스텝다운 ELS 다이렉트 배너"
        />
      </label>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="block">
          <span className="mb-1 block text-xs font-bold text-ink-3">상품군</span>
          <select className={fieldClass} value={productGroup} onChange={(event) => setProductGroup(event.target.value)}>
            {PRODUCT_GROUPS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-bold text-ink-3">채널</span>
          <select className={fieldClass} value={channel} onChange={(event) => setChannel(event.target.value)}>
            {CHANNELS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 flex items-center gap-1.5 text-xs font-bold text-ink-3">
            상품명 <span className="font-normal text-ink-4">선택</span>
          </span>
          <input
            className={fieldClass}
            type="text"
            value={selectedProduct}
            onChange={(event) => setSelectedProduct(event.target.value)}
            placeholder="예: 스텝다운 ELS 제25-118호"
          />
        </label>
      </div>

      {/* 형식 요건 안내 */}
      <div className="flex items-start gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-[12px] text-ink-3">
        <Icon name="flag" size={14} color="var(--ink-4)" style={{ marginTop: 1 }} />
        <span>
          <strong className="text-ink-2">{channelLabel}</strong> 형식 요건 — {formatHint}
        </span>
      </div>

      <label className="block">
        <span className="mb-1 flex items-center gap-1.5 text-xs font-bold text-ink-3">
          광고 문안 <span className="font-normal text-ink-4">심의 대상 원문 전체를 붙여넣으세요</span>
        </span>
        <textarea
          className={`${fieldClass} min-h-44 resize-y`}
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={8}
          placeholder="광고 제목과 본문, 고지 문구를 포함한 전체 문안을 입력합니다…"
          required
        />
        <span className="mt-1 block text-right text-[11px] text-ink-4">{text.length}자</span>
      </label>

      {noProduct && (
        <div className="rounded-lg border border-revise/40 bg-revise-bg px-3 py-2.5 text-[12px] leading-relaxed text-ink-2">
          <strong className="text-revise">상품 미선택 — 상품 사실 대조 없이 진행됩니다.</strong>
          <br />
          금리·한도 등 수치 표현의 진위는 검증되지 않으며, 표현·고지 위반만 심의합니다.
        </div>
      )}

      <div className="flex flex-wrap items-end justify-between gap-3">
        <label className="block">
          <span className="mb-1 block text-[11px] font-bold text-ink-4">판정 모델</span>
          <select
            className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12px] text-ink-2 outline-none focus:border-brand"
            value={llmModel}
            onChange={(event) => setLlmModel(event.target.value)}
          >
            {LLM_MODELS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={running || !text.trim()}
          className="flex items-center gap-2 rounded-md bg-brand px-6 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-brand/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running ? "심의 분석 중…" : "심의 분석 시작"}
          {!running && <Icon name="arrowR" size={15} />}
        </button>
      </div>
    </form>
  );
}
