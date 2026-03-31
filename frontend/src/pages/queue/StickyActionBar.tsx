import { Info, Loader2, Send } from "lucide-react";
import Button from "../../components/ui/Button";
import ScheduleDropdown from "./ScheduleDropdown";

interface SendProgress {
  sent: number;
  total: number;
  failed: number;
}

interface StickyActionBarProps {
  selectedCount: number;
  sendPhase: string;
  sendProgress: SendProgress | null;
  undoCountdown: number | null;
  schedulePending: boolean;
  scheduleError: Error | null;
  onDeselectAll: () => void;
  onReview: () => void;
  onCancel: () => void;
  onUndo: () => void;
  onReset: () => void;
  onSchedule: (value: string) => void;
}

export default function StickyActionBar({
  selectedCount,
  sendPhase,
  sendProgress,
  undoCountdown,
  schedulePending,
  scheduleError,
  onDeselectAll,
  onReview,
  onCancel,
  onUndo,
  onReset,
  onSchedule,
}: StickyActionBarProps) {
  const hasSelections = selectedCount > 0;

  return (
    <div className="fixed bottom-0 left-0 md:left-56 right-0 bg-white border-t border-gray-200 px-6 py-3 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.05)] z-40" aria-live="polite">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        {/* Left side -- status */}
        <div className="flex items-center gap-3">
          {sendPhase === "idle" && (
            <>
              <span className="text-sm font-medium text-gray-700">
                {selectedCount} selected
              </span>
              <button
                onClick={onDeselectAll}
                className="text-xs text-blue-600 hover:text-blue-700 underline"
              >
                Deselect all
              </button>
            </>
          )}
          {sendPhase === "approving" && (
            <span className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 size={14} className="animate-spin" /> Validating...
            </span>
          )}
          {sendPhase === "sending" && sendProgress && (
            <span className="flex items-center gap-2 text-sm text-blue-600">
              <Loader2 size={14} className="animate-spin" />
              Sending... {sendProgress.sent} of {sendProgress.total}
              <span title="If interrupted, unsent items stay in your queue."><Info size={14} className="text-gray-400" /></span>
            </span>
          )}
          {sendPhase === "done" && sendProgress && (
            <span className={`text-sm font-medium ${sendProgress.failed > 0 ? "text-amber-600" : "text-green-600"}`}>
              {sendProgress.failed > 0
                ? `${sendProgress.sent} sent, ${sendProgress.failed} failed`
                : `${sendProgress.sent} sent`}
            </span>
          )}
          {sendPhase === "aborted" && sendProgress && (
            <span className="text-sm text-amber-600">
              Cancelled. {sendProgress.sent} of {sendProgress.total} sent. Remaining items still in queue.
            </span>
          )}
          {sendPhase === "error" && (
            <span className="text-sm text-red-600">
              Send failed. {sendProgress ? `${sendProgress.sent} sent before error.` : ""}
            </span>
          )}
          {scheduleError && (
            <span className="text-sm text-red-600">
              {scheduleError.message}
            </span>
          )}
        </div>

        {/* Right side -- actions */}
        <div className="flex items-center gap-2">
          {/* Sending: Cancel button */}
          {sendPhase === "sending" && (
            <Button variant="secondary" size="md" onClick={onCancel}>
              Cancel
            </Button>
          )}

          {/* Done: Undo + Retry */}
          {sendPhase === "done" && undoCountdown !== null && undoCountdown > 0 && (
            <Button variant="secondary" size="md" onClick={onUndo}>
              Undo ({undoCountdown}s)
            </Button>
          )}
          {sendPhase === "done" && sendProgress && sendProgress.failed > 0 && (
            <Button variant="secondary" size="md" onClick={onReset}>
              Retry failed
            </Button>
          )}

          {/* Aborted/Error: Reset */}
          {(sendPhase === "aborted" || sendPhase === "error") && (
            <Button variant="secondary" size="md" onClick={onReset}>
              Dismiss
            </Button>
          )}

          {/* Idle: Schedule + Review & Send */}
          {sendPhase === "idle" && hasSelections && (
            <>
              <ScheduleDropdown
                isPending={schedulePending}
                onSchedule={onSchedule}
              />
              <Button
                variant="primary"
                size="lg"
                onClick={onReview}
                leftIcon={<Send size={16} />}
              >
                Review & Send {selectedCount}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
