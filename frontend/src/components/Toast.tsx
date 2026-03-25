import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { CheckCircle, XCircle, Info } from "lucide-react";

type ToastType = "success" | "error" | "info";

interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
}

interface ToastContextValue {
  toast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let nextId = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const toast = useCallback((message: string, type: ToastType = "info") => {
    const id = nextId++;
    setToasts((prev) => [...prev, { id, message, type }]);
  }, []);

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      {createPortal(
        <div className="fixed bottom-4 right-4 z-[100] flex flex-col-reverse gap-2 max-w-sm">
          {toasts.map((t) => (
            <ToastNotification
              key={t.id}
              item={t}
              onDismiss={() => removeToast(t.id)}
            />
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

const DURATION = 4000;

const iconMap: Record<ToastType, ReactNode> = {
  success: <CheckCircle size={16} className="shrink-0" />,
  error: <XCircle size={16} className="shrink-0" />,
  info: <Info size={16} className="shrink-0" />,
};

const colorClasses: Record<ToastType, string> = {
  success: "bg-green-600",
  error: "bg-red-600",
  info: "bg-blue-600",
};

const progressColors: Record<ToastType, string> = {
  success: "bg-green-400",
  error: "bg-red-400",
  info: "bg-blue-400",
};

function ToastNotification({
  item,
  onDismiss,
}: {
  item: ToastItem;
  onDismiss: () => void;
}) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, DURATION);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <div
      className={`${colorClasses[item.type]} text-white rounded-lg shadow-lg text-sm font-medium overflow-hidden animate-slide-in`}
      role="alert"
    >
      <div className="px-4 py-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {iconMap[item.type]}
          <span>{item.message}</span>
        </div>
        <button
          onClick={onDismiss}
          className="text-white/70 hover:text-white shrink-0"
          aria-label="Dismiss"
        >
          &times;
        </button>
      </div>
      <div className="h-0.5 bg-white/20">
        <div
          className={`h-full ${progressColors[item.type]} animate-toast-progress`}
        />
      </div>
    </div>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return ctx;
}
