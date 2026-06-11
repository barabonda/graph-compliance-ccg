"use client";

import { useState, type FormEvent } from "react";
import { CHANNELS, EXAMPLES, PRODUCT_GROUPS, WORKSPACE_ID, type ExamplePreset } from "@/lib/labels";
import type { ReviewRequest } from "@/lib/types";

interface Props {
  running: boolean;
  onSubmit: (payload: ReviewRequest) => void;
  onLoadSample?: () => void;
}

const DEFAULT_EXAMPLE = EXAMPLES[1];

export function ReviewForm({ running, onSubmit, onLoadSample }: Props) {
  const [title, setTitle] = useState(DEFAULT_EXAMPLE.title);
  const [productGroup, setProductGroup] = useState(DEFAULT_EXAMPLE.product);
  const [channel, setChannel] = useState(DEFAULT_EXAMPLE.channel);
  const [selectedProduct, setSelectedProduct] = useState(DEFAULT_EXAMPLE.selectedProduct);
  const [text, setText] = useState(DEFAULT_EXAMPLE.text);

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
    });
  };

  const fieldClass =
    "w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand focus:ring-2 focus:ring-brand/20";

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-3 md:grid-cols-12">
      <label className="md:col-span-4">
        <span className="mb-1 block text-xs font-bold text-ink-3">제목</span>
        <input
          className={fieldClass}
          type="text"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="예: JB시니어우대예금 특판 문안"
        />
      </label>
      <label className="md:col-span-2">
        <span className="mb-1 block text-xs font-bold text-ink-3">상품군</span>
        <select className={fieldClass} value={productGroup} onChange={(event) => setProductGroup(event.target.value)}>
          {PRODUCT_GROUPS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      <label className="md:col-span-3">
        <span className="mb-1 block text-xs font-bold text-ink-3">채널</span>
        <select className={fieldClass} value={channel} onChange={(event) => setChannel(event.target.value)}>
          {CHANNELS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      <label className="md:col-span-3">
        <span className="mb-1 block text-xs font-bold text-ink-3">선택 상품명</span>
        <input
          className={fieldClass}
          type="text"
          value={selectedProduct}
          onChange={(event) => setSelectedProduct(event.target.value)}
          placeholder="예: (26년 JUMP UP) 특판 예금"
        />
      </label>
      <label className="md:col-span-12">
        <span className="mb-1 block text-xs font-bold text-ink-3">광고 문안</span>
        <textarea
          className={`${fieldClass} min-h-28 resize-y`}
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={5}
          required
        />
      </label>
      <div className="flex flex-wrap items-center justify-between gap-3 md:col-span-12">
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <button
              key={example.label}
              type="button"
              onClick={() => fillExample(example)}
              className="rounded-full border border-line bg-surface-2 px-3 py-1 text-xs font-semibold text-ink-3 hover:border-brand hover:text-brand"
            >
              {example.label}
            </button>
          ))}
          {onLoadSample && (
            <button
              type="button"
              onClick={onLoadSample}
              className="rounded-full border border-dashed border-line px-3 py-1 text-xs font-semibold text-ink-3 hover:border-brand hover:text-brand"
              title="백엔드 호출 없이 저장된 샘플 리뷰 결과를 불러옵니다"
            >
              샘플 결과 보기
            </button>
          )}
        </div>
        <button
          type="submit"
          disabled={running || !text.trim()}
          className="rounded-md bg-brand px-6 py-2 text-sm font-bold text-white shadow-sm transition hover:bg-brand/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running ? "Reviewing..." : "Review"}
        </button>
      </div>
    </form>
  );
}
