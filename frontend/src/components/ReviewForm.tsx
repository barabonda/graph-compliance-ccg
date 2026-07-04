"use client";

import { useEffect, useState, type FormEvent } from "react";
import { getActor } from "@/lib/actor";
import { searchProducts } from "@/lib/api";
import { BANKS, CHANNELS, EXAMPLES, KH_WORKSPACE_ID, LLM_MODELS, PRODUCT_GROUPS, type BankValue, type ExamplePreset } from "@/lib/labels";
import type { ProductSearchResult, ReviewRequest } from "@/lib/types";
import { Icon } from "./Icon";

interface Props {
  running: boolean;
  onSubmit: (payload: ReviewRequest, options?: { stayOnNew?: boolean }) => Promise<boolean>;
  draftPreset?: Partial<ReviewRequest> | null;
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

export function ReviewForm({ running, onSubmit, draftPreset, onLoadSample, onLoadProductSample }: Props) {
  const [title, setTitle] = useState(draftPreset?.title ?? DEFAULT_EXAMPLE.title);
  const [productGroup, setProductGroup] = useState(draftPreset?.product_group ?? DEFAULT_EXAMPLE.product);
  const [channel, setChannel] = useState(draftPreset?.channel ?? DEFAULT_EXAMPLE.channel);
  const [selectedProduct, setSelectedProduct] = useState(draftPreset?.selected_product_name ?? DEFAULT_EXAMPLE.selectedProduct);
  const [productQuery, setProductQuery] = useState(draftPreset?.selected_product_name ?? DEFAULT_EXAMPLE.selectedProduct);
  const [productResults, setProductResults] = useState<ProductSearchResult[]>([]);
  const [productLoading, setProductLoading] = useState(false);
  const [productOpen, setProductOpen] = useState(false);
  const [productSearchError, setProductSearchError] = useState("");
  const [text, setText] = useState(draftPreset?.content_text ?? DEFAULT_EXAMPLE.text);
  const [llmModel, setLlmModel] = useState(draftPreset?.llm_model ?? "");
  // 은행(심사 주체). 재실행 프리셋의 workspace_id가 KH면 프놈펜상업은행으로 복원.
  const [bank, setBank] = useState<BankValue>(
    draftPreset?.workspace_id === KH_WORKSPACE_ID ? "ppcbank" : "jeonbuk",
  );
  const [draftQueue, setDraftQueue] = useState<ReviewRequest[]>([]);
  const [queueRunning, setQueueRunning] = useState(false);
  // 이미지 광고 접수(멀티모달): base64(data: 프리픽스 제외)와 미리보기 URL.
  const [adImage, setAdImage] = useState<{ base64: string; mediaType: string; preview: string; name: string } | null>(null);
  const [imageError, setImageError] = useState("");

  const handleImageFile = (file: File | null) => {
    setImageError("");
    if (!file) {
      setAdImage(null);
      return;
    }
    if (!/^image\/(png|jpeg|jpg|webp)$/.test(file.type)) {
      setImageError("PNG/JPEG/WebP 이미지만 첨부할 수 있습니다.");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setImageError("이미지는 8MB 이하만 첨부할 수 있습니다.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result || "");
      const base64 = dataUrl.split(",", 2)[1] ?? "";
      setAdImage({
        base64,
        mediaType: file.type === "image/jpg" ? "image/jpeg" : file.type,
        preview: dataUrl,
        name: file.name,
      });
    };
    reader.readAsDataURL(file);
  };

  // 프리셋/빠른 시나리오의 이미지 광고 — public 경로 이미지를 불러와 첨부 상태로 만든다.
  const loadImageFromUrl = async (url: string) => {
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const name = url.split("/").pop() || "ad-image.png";
      handleImageFile(new File([blob], name, { type: blob.type || "image/png" }));
    } catch {
      setImageError("프리셋 이미지를 불러오지 못했습니다.");
    }
  };

  useEffect(() => {
    if (draftPreset?.image_url) void loadImageFromUrl(draftPreset.image_url);
    // 폼은 draftPreset 별로 key 리마운트되므로 mount 시 1회면 충분하다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fillExample = (example: ExamplePreset) => {
    setTitle(example.title);
    setProductGroup(example.product);
    setChannel(example.channel);
    setSelectedProduct(example.selectedProduct);
    setProductQuery(example.selectedProduct);
    setProductOpen(false);
    setText(example.text);
    if (example.imageUrl) {
      void loadImageFromUrl(example.imageUrl);
    } else {
      handleImageFile(null);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setProductLoading(true);
      setProductSearchError("");
      searchProducts(productQuery, productGroup, controller.signal)
        .then((products) => setProductResults(products))
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          setProductSearchError(error instanceof Error ? error.message : "상품 검색에 실패했습니다.");
          setProductResults([]);
        })
        .finally(() => setProductLoading(false));
    }, 220);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [productGroup, productQuery]);

  const chooseProduct = (product: ProductSearchResult) => {
    setSelectedProduct(product.product);
    setProductQuery(product.product);
    setProductOpen(false);
  };

  const clearSelectedProduct = () => {
    setSelectedProduct("");
    setProductQuery("");
    setProductOpen(true);
  };

  const buildPayload = (): ReviewRequest => {
    const selectedBank = BANKS.find((item) => item.value === bank) ?? BANKS[0];
    return {
      dataset_item_id: `console_${Date.now()}`,
      title,
      content_text: text,
      channel,
      product_group: productGroup,
      selected_product_name: selectedProduct.trim(),
      workspace_id: selectedBank.workspaceId,
      language: selectedBank.language,
      llm_model: llmModel || undefined,
      actor: getActor(),
      image_base64: adImage?.base64 || undefined,
      image_media_type: adImage?.mediaType || undefined,
    };
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if ((!text.trim() && !adImage) || running || queueRunning) return;
    void onSubmit(buildPayload());
  };

  const addToQueue = () => {
    if (!text.trim() && !adImage) return;
    setDraftQueue((items) => [...items, { ...buildPayload(), dataset_item_id: `queue_${Date.now()}_${items.length + 1}` }]);
  };

  const removeQueuedDraft = (datasetItemId: string) => {
    setDraftQueue((items) => items.filter((item) => item.dataset_item_id !== datasetItemId));
  };

  const runQueue = async () => {
    if (!draftQueue.length || running || queueRunning) return;
    setQueueRunning(true);
    const items = [...draftQueue];
    setDraftQueue([]);
    try {
      for (const [index, item] of items.entries()) {
        await onSubmit(
          {
            ...item,
            dataset_item_id: `${item.dataset_item_id}_${Date.now()}_${index + 1}`,
            actor: item.actor || getActor(),
          },
          { stayOnNew: true },
        );
      }
    } finally {
      setQueueRunning(false);
    }
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

      <label className="block">
        <span className="mb-1 block text-xs font-bold text-ink-3">은행</span>
        <select
          className={fieldClass}
          value={bank}
          onChange={(event) => setBank(event.target.value as BankValue)}
        >
          {BANKS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        {bank === "ppcbank" && (
          <span className="mt-1 block text-[11px] leading-relaxed text-ink-3">
            캄보디아 법령(소비자보호법·Sub-Decree 232 등) 기준으로 심사합니다. 원문 아래에 참고용
            영어·한국어 번역이 함께 표시됩니다(심사 근거는 원문 기준).
          </span>
        )}
      </label>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="block">
          <span className="mb-1 block text-xs font-bold text-ink-3">상품군</span>
          <select
            className={fieldClass}
            value={productGroup}
            onChange={(event) => {
              setProductGroup(event.target.value);
              setSelectedProduct("");
              setProductQuery("");
              setProductOpen(false);
            }}
          >
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
            상품명 <span className="font-normal text-ink-4">DB에서 검색/선택</span>
          </span>
          <div className="relative">
            <input
              className={`${fieldClass} pr-9`}
              type="search"
              value={productQuery}
              onFocus={() => setProductOpen(true)}
              onBlur={() => window.setTimeout(() => setProductOpen(false), 140)}
              onChange={(event) => {
                setProductQuery(event.target.value);
                setSelectedProduct("");
                setProductOpen(true);
              }}
              placeholder="예: JB도전루틴적금"
              autoComplete="off"
            />
            {selectedProduct ? (
              <button
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={clearSelectedProduct}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full px-1.5 text-xs font-bold text-ink-4 hover:bg-surface-2 hover:text-ink"
                aria-label="선택 상품 지우기"
              >
                ×
              </button>
            ) : null}
            {productOpen && (
              <div className="absolute z-30 mt-1 max-h-80 w-full overflow-auto rounded-lg border border-line bg-surface p-1.5 shadow-xl">
                {productLoading && <div className="px-3 py-2 text-xs text-ink-4">상품 DB 검색 중…</div>}
                {!productLoading && productSearchError && <div className="px-3 py-2 text-xs text-reject">{productSearchError}</div>}
                {!productLoading && !productSearchError && productResults.length === 0 && (
                  <div className="px-3 py-2 text-xs leading-relaxed text-ink-4">
                    검색 결과가 없습니다. 상품군을 바꾸거나 상품명 일부를 다시 입력해 주세요.
                  </div>
                )}
                {!productLoading &&
                  !productSearchError &&
                  productResults.map((product) => (
                    <button
                      key={`${product.product}-${product.source ?? ""}-${product.match_basis ?? ""}`}
                      type="button"
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => chooseProduct(product)}
                      className="w-full rounded-md px-3 py-2 text-left hover:bg-brand/10"
                    >
                      <span className="block text-sm font-bold text-ink">{product.product}</span>
                      <span className="mt-0.5 block truncate text-[11px] text-ink-4">
                        {product.major || product.product_group || "상품"} · 문서 {product.document_count ?? 0}개
                        {product.document_labels?.length ? ` · ${product.document_labels.slice(0, 2).join(", ")}` : ""}
                      </span>
                    </button>
                  ))}
              </div>
            )}
          </div>
          {selectedProduct ? (
            <span className="mt-1 block text-[11px] font-semibold text-pass">선택됨: {selectedProduct}</span>
          ) : productQuery.trim() ? (
            <span className="mt-1 block text-[11px] text-revise">검색 결과에서 상품을 선택해야 상품 사실 대조가 진행됩니다.</span>
          ) : (
            <span className="mt-1 block text-[11px] text-ink-4">상품 미선택 시 Product Fact 대조는 건너뜁니다.</span>
          )}
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
          광고 문안{" "}
          <span className="font-normal text-ink-4">
            {adImage ? "이미지 첨부됨 — 비워두면 이미지에서 문안을 자동 추출합니다" : "심의 대상 원문 전체를 붙여넣으세요"}
          </span>
        </span>
        <textarea
          className={`${fieldClass} min-h-44 resize-y`}
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={8}
          placeholder={
            adImage
              ? "(선택) 비워두면 첨부한 이미지에서 문안을 자동 추출해 심의합니다."
              : "광고 제목과 본문, 고지 문구를 포함한 전체 문안을 입력합니다…"
          }
          required={!adImage}
        />
        <span className="mt-1 block text-right text-[11px] text-ink-4">{text.length}자</span>
      </label>

      {/* 이미지 광고 접수(멀티모달) — 배너/전단 이미지에서 문안·레이아웃을 추출해 심의 */}
      <div className="rounded-lg border border-line bg-surface-2 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-bold text-ink-3">
            이미지 광고 <span className="font-normal text-ink-4">배너·전단 이미지로 접수 (문안 자동 추출 + 이미지 수정안 생성)</span>
          </span>
          <label className="cursor-pointer rounded-md border border-line bg-surface px-3 py-1.5 text-[12px] font-bold text-ink-2 hover:border-brand hover:text-brand">
            {adImage ? "이미지 바꾸기" : "이미지 첨부"}
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(event) => handleImageFile(event.target.files?.[0] ?? null)}
            />
          </label>
        </div>
        {imageError && <p className="mt-2 text-[12px] font-semibold text-reject">{imageError}</p>}
        {adImage && (
          <div className="mt-2 flex items-start gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={adImage.preview} alt="첨부한 광고 이미지 미리보기" className="max-h-40 rounded-md border border-line" />
            <div className="min-w-0 text-[12px] leading-relaxed text-ink-3">
              <div className="truncate font-semibold text-ink-2">{adImage.name}</div>
              <div>심의 시 이미지에서 문안을 추출하고, 심의 후 교정 문안이 반영된 이미지 수정안을 생성할 수 있습니다.</div>
              <button
                type="button"
                onClick={() => handleImageFile(null)}
                className="mt-1 rounded px-1.5 py-0.5 text-[11px] font-bold text-ink-4 hover:bg-surface hover:text-reject"
              >
                이미지 제거
              </button>
            </div>
          </div>
        )}
      </div>

      {noProduct && (
        <div className="rounded-lg border border-revise/40 bg-revise-bg px-3 py-2.5 text-[12px] leading-relaxed text-ink-2">
          <strong className="text-revise">상품 미선택 — 상품 사실 대조 없이 진행됩니다.</strong>
          <br />
          금리·한도 등 수치 표현의 진위는 검증되지 않으며, 표현·고지 위반만 심의합니다.
        </div>
      )}

      {draftQueue.length > 0 && (
        <div className="rounded-lg border border-line bg-surface-2 p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs font-extrabold text-ink">대기 중인 초안 {draftQueue.length}건</span>
            <button
              type="button"
              onClick={() => void runQueue()}
              disabled={running || queueRunning}
              className="rounded-md bg-ink px-3 py-1.5 text-[12px] font-bold text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {queueRunning ? "대기열 실행 중…" : "대기열 실행"}
            </button>
          </div>
          <div className="flex max-h-36 flex-col gap-1.5 overflow-auto">
            {draftQueue.map((item, index) => (
              <div key={item.dataset_item_id} className="flex items-center gap-2 rounded-md border border-line bg-surface px-2 py-1.5">
                <span className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[10px] font-bold text-ink-3">
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-ink-2">
                  {item.title || "(제목 없음)"} · {item.product_group} · {item.selected_product_name || "상품 미선택"}
                </span>
                <button
                  type="button"
                  onClick={() => removeQueuedDraft(item.dataset_item_id)}
                  className="rounded px-1.5 py-0.5 text-[11px] font-bold text-ink-4 hover:bg-surface-2 hover:text-reject"
                >
                  제거
                </button>
              </div>
            ))}
          </div>
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
        <div className="flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={addToQueue}
            disabled={!text.trim() && !adImage}
            className="rounded-md border border-line bg-surface px-4 py-2.5 text-sm font-bold text-ink-2 hover:border-brand hover:text-brand disabled:cursor-not-allowed disabled:opacity-50"
          >
            대기열 추가
          </button>
          <button
            type="submit"
            disabled={running || queueRunning || (!text.trim() && !adImage)}
            className="flex items-center gap-2 rounded-md bg-brand px-6 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-brand/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running || queueRunning ? "심의 분석 중…" : "심의 분석 시작"}
            {!running && !queueRunning && <Icon name="arrowR" size={15} />}
          </button>
        </div>
      </div>
    </form>
  );
}
