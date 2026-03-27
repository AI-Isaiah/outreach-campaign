import { useCallback, useEffect, useRef, useState } from "react";
import { Mail, Undo2 } from "lucide-react";
import Button from "./ui/Button";
import { queueApi } from "../api/queue";

interface UndoToastProps {
  contactIds: number[];
  count: number;
  onComplete: () => void;
  onUndo: () => void;
  onDismiss: () => void;
}

type Phase = "countdown" | "cancelling" | "success" | "error";

const COUNTDOWN_SECONDS = 30;
const SUCCESS_DISMISS_MS = 2000;

export default function UndoToast({
  contactIds,
  count,
  onComplete,
  onUndo,
  onDismiss,
}: UndoToastProps) {
  const [seconds, setSeconds] = useState(COUNTDOWN_SECONDS);
  const [phase, setPhase] = useState<Phase>("countdown");
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // --- countdown timer ---
  useEffect(() => {
    if (phase !== "countdown") return;

    intervalRef.current = setInterval(() => {
      setSeconds((prev) => {
        if (prev <= 1) {
          clearInterval(intervalRef.current!);
          intervalRef.current = null;
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [phase]);

  // --- when countdown reaches 0, fire onComplete ---
  useEffect(() => {
    if (phase === "countdown" && seconds === 0) {
      onComplete();
      onDismiss();
    }
  }, [phase, seconds, onComplete, onDismiss]);

  // --- auto-dismiss after successful undo ---
  useEffect(() => {
    if (phase !== "success") return;
    const timer = setTimeout(() => {
      onDismiss();
    }, SUCCESS_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [phase, onDismiss]);

  const handleUndo = useCallback(async () => {
    // stop countdown
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setPhase("cancelling");

    try {
      await queueApi.batchCancel(contactIds);
      setPhase("success");
      onUndo();
    } catch {
      setPhase("error");
    }
  }, [contactIds, onUndo]);

  return (
    <div
      role="alert"
      className="fixed bottom-4 right-4 z-50 bg-blue-50 border border-blue-200 rounded-lg shadow-lg p-4 max-w-sm w-full animate-in slide-in-from-bottom-4"
    >
      {phase === "countdown" && (
        <div className="flex items-center gap-3">
          <Mail size={18} className="text-blue-600 shrink-0" />
          <p className="flex-1 text-sm text-blue-800">
            Sending {count} email{count !== 1 ? "s" : ""} in{" "}
            <span className="font-semibold tabular-nums">{seconds}s</span>...
          </p>
          <Button
            variant="secondary"
            size="sm"
            leftIcon={<Undo2 size={14} />}
            onClick={handleUndo}
            aria-label={`Cancel sending ${count} email${count !== 1 ? "s" : ""}`}
          >
            Undo
          </Button>
        </div>
      )}

      {phase === "cancelling" && (
        <div className="flex items-center gap-3">
          <Mail size={18} className="text-blue-600 shrink-0" />
          <p className="flex-1 text-sm text-blue-800">Cancelling...</p>
          <Button variant="secondary" size="sm" loading disabled>
            Undo
          </Button>
        </div>
      )}

      {phase === "success" && (
        <div className="flex items-center gap-3">
          <Mail size={18} className="text-green-600 shrink-0" />
          <p className="flex-1 text-sm text-green-700 font-medium">
            Undo successful — emails cancelled
          </p>
        </div>
      )}

      {phase === "error" && (
        <div className="flex items-center gap-3">
          <Mail size={18} className="text-red-600 shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm text-red-700 font-medium">
              Undo failed — emails will send
            </p>
            <div className="mt-2">
              <Button variant="danger" size="sm" onClick={handleUndo}>
                Retry
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
