"use client";

import { useCallback, useReducer, useRef } from "react";
import { ReviewApiError, streamReview } from "@/lib/api";
import { defaultAnchorId } from "@/lib/selectors";
import type { PrincipleKey } from "@/lib/labels";
import type { ReviewOutput, ReviewRequest, StreamEvent } from "@/lib/types";

export interface ReviewState {
  status: "idle" | "running" | "done" | "error";
  result: ReviewOutput | null;
  /** Ad copy that produced `result` — highlights are computed against this. */
  reviewedText: string;
  events: StreamEvent[];
  error: { code: string; message: string; cause?: string } | null;
  selectedAnchorId: string;
  selectedPrinciple: PrincipleKey | "";
}

type Action =
  | { type: "start" }
  | { type: "event"; event: StreamEvent }
  | { type: "done"; result: ReviewOutput; reviewedText: string }
  | { type: "fail"; error: ReviewState["error"] }
  | { type: "select_anchor"; anchorId: string }
  | { type: "toggle_principle"; principle: PrincipleKey }
  | { type: "load_sample"; result: ReviewOutput; reviewedText: string };

/**
 * Long LLM calls can legitimately stay quiet for several minutes. Treat the
 * first quiet window as a UX warning, not as proof that the stream died.
 */
const STREAM_STALL_WARNING_MS = Number(process.env.NEXT_PUBLIC_REVIEW_STREAM_STALL_WARNING_MS ?? 300_000);
const STREAM_HARD_ABORT_MS = Number(process.env.NEXT_PUBLIC_REVIEW_STREAM_HARD_ABORT_MS ?? 1_200_000);
/** While the stream is quiet, probe /health on this cadence. */
const HEALTH_PROBE_INTERVAL_MS = 15_000;
/** Only probe after this much silence so fast steps don't trigger checks. */
const HEALTH_PROBE_SILENCE_MS = 20_000;

const initialState: ReviewState = {
  status: "idle",
  result: null,
  reviewedText: "",
  events: [],
  error: null,
  selectedAnchorId: "",
  selectedPrinciple: "",
};

function reducer(state: ReviewState, action: Action): ReviewState {
  switch (action.type) {
    case "start":
      return { ...initialState, status: "running" };
    case "event":
      return {
        ...state,
        events: [
          ...state.events,
          { ...action.event, received_at: new Date().toLocaleTimeString("ko-KR", { hour12: false }) },
        ],
      };
    case "done":
      return {
        ...state,
        status: "done",
        result: action.result,
        // 원문을 NFC로 정규화 — 입력이 NFD(분해형 자모)면 NFC인 앵커·제안 텍스트와
        // 바이트가 달라 하이라이트 정렬이 전부 실패한다. 표시상으로는 동일하다.
        reviewedText: action.reviewedText.normalize("NFC"),
        error: null,
        selectedAnchorId: defaultAnchorId(action.result),
        selectedPrinciple: "",
      };
    case "fail":
      return { ...state, status: "error", error: action.error };
    case "select_anchor":
      return { ...state, selectedAnchorId: action.anchorId };
    case "toggle_principle":
      return {
        ...state,
        selectedPrinciple: state.selectedPrinciple === action.principle ? "" : action.principle,
      };
    case "load_sample":
      return {
        ...initialState,
        status: "done",
        result: action.result,
        reviewedText: action.reviewedText.normalize("NFC"),
        selectedAnchorId: defaultAnchorId(action.result),
      };
    default:
      return state;
  }
}

export function useReview() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const abortRef = useRef<AbortController | null>(null);

  /** Runs a streaming review. Resolves `true` when a result was produced. */
  const runReview = useCallback(async (payload: ReviewRequest): Promise<boolean> => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    dispatch({ type: "start" });

    // Watchdog: show a soft warning while long backend LLM calls are silent,
    // but do not abort early. Some valid review runs return after the old
    // five-minute threshold.
    let hardStalled = false;
    let backendDead = false;
    let softWarningCount = 0;
    let warningWatchdog: ReturnType<typeof setTimeout> | undefined;
    let hardWatchdog: ReturnType<typeof setTimeout> | undefined;
    const scheduleSoftWarning = () => {
      clearTimeout(warningWatchdog);
      warningWatchdog = setTimeout(() => {
        softWarningCount += 1;
        dispatch({
          type: "event",
          event: {
            event: "stream_waiting",
            step: "Long-running analysis step",
            summary:
              "긴 LLM/상품문서 분석 단계가 진행 중입니다. 새 이벤트가 늦어도 연결은 유지하고 결과를 계속 기다립니다.",
            counts: { waiting_minutes: Math.round((softWarningCount * STREAM_STALL_WARNING_MS) / 60_000) },
          },
        });
        scheduleSoftWarning();
      }, STREAM_STALL_WARNING_MS);
    };
    const armWatchdog = () => {
      lastEventAt = Date.now();
      scheduleSoftWarning();
      clearTimeout(hardWatchdog);
      hardWatchdog = setTimeout(() => {
        hardStalled = true;
        controller.abort();
      }, STREAM_HARD_ABORT_MS);
    };

    // Health probe: a dead/restarted backend leaves the NDJSON stream open
    // but silent, which otherwise looks identical to a slow step until the
    // hard-abort timeout. While the stream is quiet, poll /health; two
    // consecutive failures mean the server is gone — fail fast and clearly
    // instead of hanging for the full hard-abort window.
    let lastEventAt = Date.now();
    let healthFailures = 0;
    const healthProbe = setInterval(() => {
      if (Date.now() - lastEventAt < HEALTH_PROBE_SILENCE_MS) {
        healthFailures = 0;
        return;
      }
      void fetch("/health", { cache: "no-store", signal: AbortSignal.timeout(5_000) })
        .then((response) => {
          healthFailures = response.ok ? 0 : healthFailures + 1;
          if (healthFailures >= 2) {
            backendDead = true;
            controller.abort();
          }
        })
        .catch(() => {
          healthFailures += 1;
          if (healthFailures >= 2) {
            backendDead = true;
            controller.abort();
          }
        });
    }, HEALTH_PROBE_INTERVAL_MS);
    armWatchdog();

    let result: ReviewOutput | null = null;
    try {
      await streamReview(
        payload,
        (event) => {
          armWatchdog();
          dispatch({ type: "event", event });
          if (event.event === "result" && event.result) {
            result = event.result;
          }
        },
        controller.signal,
      );
      if (!result) {
        throw new ReviewApiError(
          "review_stream_finished_without_result",
          "스트림이 결과 이벤트 없이 종료됐습니다. 네트워크가 끊겼을 수 있으니 다시 실행해 주세요.",
        );
      }
      dispatch({ type: "done", result, reviewedText: payload.content_text });
      return true;
    } catch (error) {
      if (controller.signal.aborted) {
        if (backendDead) {
          dispatch({
            type: "fail",
            error: {
              code: "backend_unreachable",
              message:
                "백엔드 서버가 응답하지 않습니다(연결 끊김). 분석 도중 서버가 종료됐을 수 있습니다. 서버를 재시작한 뒤 다시 실행해 주세요.",
            },
          });
        } else if (hardStalled) {
          dispatch({
            type: "fail",
            error: {
              code: "review_stream_stalled",
              message: `${Math.round(STREAM_HARD_ABORT_MS / 1000)}초 동안 진행 이벤트가 없어 연결이 끊긴 것으로 판단했습니다. 백엔드는 계속 처리 중일 수 있으니 잠시 후 다시 실행해 주세요.`,
            },
          });
        }
        return false;
      }
      if (error instanceof ReviewApiError) {
        dispatch({ type: "fail", error: { code: error.code, message: error.message, cause: error.cause } });
      } else {
        dispatch({
          type: "fail",
          error: { code: "review_failed", message: error instanceof Error ? error.message : String(error) },
        });
      }
      return false;
    } finally {
      clearTimeout(warningWatchdog);
      clearTimeout(hardWatchdog);
      clearInterval(healthProbe);
    }
  }, []);

  const selectAnchor = useCallback((anchorId: string) => dispatch({ type: "select_anchor", anchorId }), []);
  const togglePrinciple = useCallback(
    (principle: PrincipleKey) => dispatch({ type: "toggle_principle", principle }),
    [],
  );
  const loadSample = useCallback(
    (result: ReviewOutput, reviewedText: string) => dispatch({ type: "load_sample", result, reviewedText }),
    [],
  );

  return { state, runReview, selectAnchor, togglePrinciple, loadSample };
}
