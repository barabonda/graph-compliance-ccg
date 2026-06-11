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
 * No stream event for this long → treat the connection as dead.
 * Backend LLM calls are capped at CCG_OPENAI_TIMEOUT_SECONDS (120s) x retries,
 * so a healthy run never goes silent for 5 minutes.
 */
const STREAM_STALL_MS = 300_000;

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
        reviewedText: action.reviewedText,
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
        reviewedText: action.reviewedText,
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

    // Stall watchdog: a silently dropped stream otherwise leaves the UI on
    // "running" forever. The slowest single step (product fact extraction)
    // is bounded by the backend LLM timeout, so a long silence means the
    // connection is dead, not that work is in progress.
    let stalled = false;
    let watchdog: ReturnType<typeof setTimeout> | undefined;
    const armWatchdog = () => {
      clearTimeout(watchdog);
      watchdog = setTimeout(() => {
        stalled = true;
        controller.abort();
      }, STREAM_STALL_MS);
    };
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
        if (stalled) {
          dispatch({
            type: "fail",
            error: {
              code: "review_stream_stalled",
              message: `${Math.round(STREAM_STALL_MS / 1000)}초 동안 진행 이벤트가 없어 연결이 끊긴 것으로 판단했습니다. 백엔드는 계속 처리 중일 수 있으니 잠시 후 다시 실행해 주세요.`,
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
      clearTimeout(watchdog);
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
