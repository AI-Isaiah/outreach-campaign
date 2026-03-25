import { AlertTriangle } from "lucide-react";
import Button from "./Button";

interface ErrorCardProps {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}

export default function ErrorCard({
  message,
  onRetry,
  retryLabel = "Try Again",
}: ErrorCardProps) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3">
      <AlertTriangle size={18} className="text-red-600 shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-red-700">{message}</p>
        {onRetry && (
          <div className="mt-3">
            <Button variant="danger" size="sm" onClick={onRetry}>
              {retryLabel}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
