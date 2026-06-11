import type { CSSProperties, ReactNode } from "react";

/** 레퍼런스 디자인의 최소 라인 아이콘 세트. */
const PATHS: Record<string, ReactNode> = {
  review: (
    <>
      <path d="M4 5h11M4 10h7M4 15h9M4 20h5" />
      <circle cx="17.5" cy="16.5" r="3.5" />
      <path d="m20.5 19.5 2 2" />
    </>
  ),
  graph: (
    <>
      <circle cx="5" cy="6" r="2" />
      <circle cx="5" cy="18" r="2" />
      <circle cx="19" cy="12" r="2" />
      <path d="M7 6.6 17 11M7 17.4 17 13" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3 5 6v5c0 4.2 2.8 7.6 7 9 4.2-1.4 7-4.8 7-9V6l-7-3Z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  dashboard: (
    <>
      <rect x="3" y="3" width="8" height="8" rx="1.5" />
      <rect x="13" y="3" width="8" height="5" rx="1.5" />
      <rect x="13" y="11" width="8" height="10" rx="1.5" />
      <rect x="3" y="14" width="8" height="7" rx="1.5" />
    </>
  ),
  audit: (
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5M9 13h6M9 17h4" />
    </>
  ),
  check: <path d="m5 12 4.5 4.5L19 7" />,
  x: <path d="M6 6l12 12M18 6 6 18" />,
  alert: (
    <>
      <path d="M12 8v5" />
      <circle cx="12" cy="16.5" r=".6" fill="currentColor" stroke="none" />
      <path d="M10.3 4 3.5 16a2 2 0 0 0 1.7 3h13.6a2 2 0 0 0 1.7-3L13.7 4a2 2 0 0 0-3.4 0Z" />
    </>
  ),
  flag: <path d="M5 21V4M5 4h11l-2 3.5L16 11H5" />,
  spark: (
    <path d="M12 3v4m0 10v4m9-9h-4M7 12H3m13.5-6.5-2.8 2.8M9.3 14.7l-2.8 2.8m11 0-2.8-2.8M9.3 9.3 6.5 6.5" />
  ),
  arrowR: <path d="M5 12h14m0 0-5-5m5 5-5 5" />,
  clause: (
    <>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </>
  ),
  layers: (
    <>
      <path d="m12 3 8 4.5-8 4.5-8-4.5L12 3Z" />
      <path d="m4 12 8 4.5 8-4.5M4 16.5 12 21l8-4.5" />
    </>
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="12" cy="12" r=".6" fill="currentColor" stroke="none" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20c0-3.5 3.1-5.5 7-5.5s7 2 7 5.5" />
    </>
  ),
  eye: (
    <>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
      <circle cx="12" cy="12" r="2.8" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </>
  ),
};

export function Icon({
  name,
  size = 20,
  stroke = 1.7,
  color = "currentColor",
  style,
}: {
  name: keyof typeof PATHS | string;
  size?: number;
  stroke?: number;
  color?: string;
  style?: CSSProperties;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
      aria-hidden
    >
      {PATHS[name] ?? null}
    </svg>
  );
}
