// 실행자(심사자) 가명. 인증 없이 브라우저별로 안정적인 가명을 부여한다
// (Vercel 익명 접속자도 자동으로 구분되어 실행 기록에 표시됨). localStorage 보관.

const KEY = "ccg_actor";

const ALIASES = [
  "우리 집 누렁이",
  "순정토끼",
  "슬리피 베어",
  "고구마 말랭이",
  "소금빵",
  "정신없는 햄스터",
  "피곤한 낙타",
  "숲속의 벨루가",
  "츄러스 너구리",
  "졸린 카피바라",
  "통통 도토리",
  "야근하는 펭귄",
  "말차라떼 수달",
  "구름 위 알파카",
  "단호한 고슴도치",
];

/** 브라우저별 안정적인 가명. 없으면 풀에서 하나 골라 저장. SSR에서는 빈 문자열. */
export function getActor(): string {
  if (typeof window === "undefined") return "";
  try {
    let value = window.localStorage.getItem(KEY);
    if (!value) {
      value = ALIASES[Math.floor(Math.random() * ALIASES.length)];
      window.localStorage.setItem(KEY, value);
    }
    return value;
  } catch {
    return "익명 심사자";
  }
}
