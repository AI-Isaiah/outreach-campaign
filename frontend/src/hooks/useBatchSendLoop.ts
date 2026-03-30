import { useRef, useState, useEffect, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { queueApi } from "../api/queue";
import type { QueueItem, BatchValidationErrors } from "../types";

/*
 * Send Phase State Machine:
 *
 *   idle ──→ approving ──→ sending ──→ done
 *     │          │            │          │
 *     │          ▼            ▼          ▼
 *     │        idle         aborted    idle (after 30s)
 *     │       (on 400)     (on cancel)
 *     │          │            │
 *     │          ▼            ▼
 *     │        idle         idle
 *     │       (user fixes) (user retries)
 *     │
 *     └──────────────────→ error (on network/401)
 *
 * Valid transitions:
 *   idle → approving (user clicks Send)
 *   approving → idle (validation 400, user fixes selection)
 *   approving → sending (approval succeeds)
 *   sending → done (all batches complete)
 *   sending → aborted (user clicks Cancel or Undo)
 *   sending → error (network failure, 401)
 *   done → idle (undo countdown expires or undo completes)
 *   aborted → idle (user acknowledges)
 *   error → idle (user retries or dismisses)
 */

export type SendPhase = "idle" | "approving" | "sending" | "done" | "aborted" | "error";

interface SendProgress {
  sent: number;
  failed: number;
  total: number;
}

interface UseBatchSendLoopReturn {
  sendPhase: SendPhase;
  sendProgress: SendProgress | null;
  validationErrors: BatchValidationErrors | null;
  undoCountdown: number | null;
  handleConfirmSend: (force: boolean, selectedItems: QueueItem[], selectedIds: Set<number>) => Promise<void>;
  handleCancel: () => void;
  handleUndo: () => Promise<void>;
  handleRetry: (selectedItems: QueueItem[], selectedIds: Set<number>) => Promise<void>;
  resetState: () => void;
}

export function useBatchSendLoop(): UseBatchSendLoopReturn {
  const queryClient = useQueryClient();

  const [sendPhase, setSendPhase] = useState<SendPhase>("idle");
  const [sendProgress, setSendProgress] = useState<SendProgress | null>(null);
  const [validationErrors, setBatchValidationErrors] = useState<BatchValidationErrors | null>(null);
  const [undoCountdown, setUndoCountdown] = useState<number | null>(null);

  // Refs for loop-internal state (avoids stale closures)
  const abortRef = useRef<AbortController | null>(null);
  const sentRef = useRef(0);
  const failedRef = useRef(0);
  const phaseRef = useRef<SendPhase>("idle");

  // Keep phaseRef in sync with state
  useEffect(() => {
    phaseRef.current = sendPhase;
  }, [sendPhase]);

  // Undo countdown timer
  useEffect(() => {
    if (undoCountdown === null || undoCountdown <= 0) return;
    const timer = setTimeout(() => setUndoCountdown((c) => (c ?? 1) - 1), 1000);
    return () => clearTimeout(timer);
  }, [undoCountdown]);

  // Countdown expiry: reset to idle
  useEffect(() => {
    if (undoCountdown === 0) {
      setUndoCountdown(null);
      setSendPhase("idle");
      setSendProgress(null);
    }
  }, [undoCountdown]);

  const handleConfirmSend = useCallback(async (
    force: boolean,
    selectedItems: QueueItem[],
    selectedIds: Set<number>,
  ) => {
    // 1. Approve
    setSendPhase("approving");
    phaseRef.current = "approving";
    setBatchValidationErrors(null);

    const pairs = selectedItems
      .filter((i) => selectedIds.has(i.contact_id))
      .map((i) => ({ contact_id: i.contact_id, campaign_id: i.campaign_id! }));

    try {
      const approveResult = await queueApi.batchApprove(pairs, force);
      if (approveResult.validation_errors) {
        setBatchValidationErrors(approveResult.validation_errors);
        setSendPhase("idle");
        phaseRef.current = "idle";
        return;
      }
    } catch {
      setSendPhase("error");
      phaseRef.current = "error";
      return;
    }

    // 2. Send loop
    setSendPhase("sending");
    phaseRef.current = "sending";
    abortRef.current = new AbortController();
    sentRef.current = 0;
    failedRef.current = 0;
    const total = pairs.length;

    let remaining = Infinity;
    while (remaining > 0) {
      if (abortRef.current.signal.aborted) {
        setSendPhase("aborted");
        phaseRef.current = "aborted";
        break;
      }
      try {
        const result = await queueApi.batchSend({ signal: abortRef.current.signal });
        sentRef.current += result.sent;
        failedRef.current += result.failed;
        remaining = result.remaining;
        setSendProgress({ sent: sentRef.current, failed: failedRef.current, total });
        // Safety: no progress made, avoid infinite loop
        if (result.sent === 0 && remaining > 0) break;
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") {
          setSendPhase("aborted");
          phaseRef.current = "aborted";
        } else {
          setSendPhase("error");
          phaseRef.current = "error";
        }
        break;
      }
    }

    // If loop completed normally
    if (phaseRef.current === "sending") {
      setSendPhase("done");
      phaseRef.current = "done";
      setUndoCountdown(30);
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    }
  }, [queryClient]);

  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const handleUndo = useCallback(async () => {
    // Abort first if still sending
    if (phaseRef.current === "sending") {
      abortRef.current?.abort();
    }
    try {
      await queueApi.undoSend();
      setSendPhase("idle");
      phaseRef.current = "idle";
      setSendProgress(null);
      setUndoCountdown(null);
      setBatchValidationErrors(null);
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    } catch (err) {
      console.error("Undo failed:", err);
      // Don't silently swallow — user needs to know
    }
  }, [queryClient]);

  const handleRetry = useCallback(async (
    selectedItems: QueueItem[],
    selectedIds: Set<number>,
  ) => {
    setSendPhase("idle");
    phaseRef.current = "idle";
    setSendProgress(null);
    setBatchValidationErrors(null);
    await handleConfirmSend(false, selectedItems, selectedIds);
  }, [handleConfirmSend]);

  const resetState = useCallback(() => {
    setSendPhase("idle");
    phaseRef.current = "idle";
    setSendProgress(null);
    setBatchValidationErrors(null);
    setUndoCountdown(null);
    abortRef.current = null;
  }, []);

  return {
    sendPhase,
    sendProgress,
    validationErrors,
    undoCountdown,
    handleConfirmSend,
    handleCancel,
    handleUndo,
    handleRetry,
    resetState,
  };
}
