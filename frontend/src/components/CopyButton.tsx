import { useState, useRef, useEffect } from "react";
import { Check } from "lucide-react";

export default function CopyButton({
  text,
  variant = "default",
  ariaLabel,
}: {
  text: string;
  variant?: "default" | "primary";
  ariaLabel?: string;
}) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(false), 2000);
  };

  const baseClasses = "px-3 py-1.5 rounded-md text-sm font-medium transition-colors inline-flex items-center gap-1.5";

  const variantClasses = copied
    ? "bg-green-100 text-green-700"
    : variant === "primary"
      ? "bg-blue-600 text-white hover:bg-blue-700"
      : "bg-gray-100 text-gray-700 hover:bg-gray-200";

  return (
    <button
      onClick={handleCopy}
      className={`${baseClasses} ${variantClasses}`}
      aria-label={ariaLabel}
    >
      {copied && <Check size={14} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}
