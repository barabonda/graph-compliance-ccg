"use client";

import { useEffect } from "react";
import { tr, useLocale } from "@/lib/i18n";

/** 광고 이미지 확대 뷰 — 배경 클릭 또는 ESC로 닫기. 표시 전용(포털 없이 fixed). */
export function ImageLightbox({
  src,
  alt,
  caption,
  downloadName,
  onClose,
}: {
  src: string;
  alt: string;
  caption?: string;
  downloadName?: string;
  onClose: () => void;
}) {
  const locale = useLocale();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-black/75 p-6 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={alt}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt}
        className="max-h-[84vh] max-w-[94vw] rounded-lg bg-white object-contain shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      />
      <div className="flex items-center gap-3" onClick={(event) => event.stopPropagation()}>
        {caption && <span className="text-[13px] font-semibold text-white/90">{caption}</span>}
        {downloadName && (
          <a
            href={src}
            download={downloadName}
            className="rounded-md bg-white/15 px-3 py-1.5 text-[12.5px] font-bold text-white transition hover:bg-white/30"
          >
            {tr(locale, "다운로드", "Download")}
          </a>
        )}
        <button
          type="button"
          onClick={onClose}
          className="rounded-md bg-white/15 px-3 py-1.5 text-[12.5px] font-bold text-white transition hover:bg-white/30"
        >
          {tr(locale, "닫기 (ESC)", "Close (ESC)")}
        </button>
      </div>
    </div>
  );
}
