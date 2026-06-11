"use client";

import { useEffect } from "react";

export function Toast({ message, onDone }: { message: string; onDone: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDone, 2600);
    return () => clearTimeout(timer);
  }, [message, onDone]);
  return (
    <div
      className="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-[10px] bg-ink px-4.5 py-2.5 text-[13.5px] font-semibold text-white shadow-lg"
      style={{ animation: "toastIn .25s" }}
    >
      <span className="text-[#7fe3b8]">✓</span> {message}
    </div>
  );
}
