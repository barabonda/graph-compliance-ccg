// 실행자(심사자) 가명. 인증 없이 브라우저별로 안정적인 가명을 부여한다
// (Vercel 익명 접속자도 자동으로 구분되어 실행 기록에 표시됨). localStorage 보관.

const KEY = "ccg_actor";

const ALIASES = [
  "가람",
  "나래",
  "다온",
  "라온",
  "미르",
  "바다",
  "사랑",
  "아라",
  "온누리",
  "별찬",
  "한별",
  "슬기",
  "도담",
  "하랑",
];

/** 브라우저별 안정적인 가명. 없으면 생성해 저장. SSR에서는 빈 문자열. */
export function getActor(): string {
  if (typeof window === "undefined") return "";
  try {
    let value = window.localStorage.getItem(KEY);
    if (!value) {
      const alias = ALIASES[Math.floor(Math.random() * ALIASES.length)];
      const id = Math.random().toString(36).slice(2, 5).toUpperCase();
      value = `심사자 ${alias}-${id}`;
      window.localStorage.setItem(KEY, value);
    }
    return value;
  } catch {
    return "심사자";
  }
}
