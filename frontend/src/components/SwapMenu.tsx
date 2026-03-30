import { useState, useRef, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Loader2 } from "lucide-react";
import { queueApi } from "../api/queue";

interface SwapCandidate {
  id: number;
  full_name: string;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  linkedin_url: string | null;
  title: string | null;
  priority_rank: number | null;
}

export default function SwapMenu({
  contactId,
  campaignId,
}: {
  contactId: number;
  campaignId: number;
}) {
  const [open, setOpen] = useState(false);
  const [candidates, setCandidates] = useState<SwapCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const swapMutation = useMutation({
    mutationFn: (replacementId: number) =>
      queueApi.swapContact(contactId, replacementId, campaignId),
    onSuccess: () => {
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ["queue-all"] });
    },
  });

  const handleToggle = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await queueApi.getSwapCandidates(contactId, campaignId);
      setCandidates(data.candidates);
      if (data.candidates.length === 0) {
        setError("No swap candidates at this company");
      }
      setOpen(true);
    } catch {
      setError("Failed to load candidates");
      setOpen(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={handleToggle}
        disabled={loading || swapMutation.isPending}
        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs text-gray-500 border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-50 transition-colors"
        title="Swap with another contact at this company"
      >
        {loading || swapMutation.isPending ? (
          <Loader2 size={12} className="animate-spin" />
        ) : (
          <RefreshCw size={12} />
        )}
        Swap
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 w-72 bg-white border border-gray-200 rounded-lg shadow-lg z-10">
          {error && candidates.length === 0 ? (
            <div className="px-3 py-2 text-sm text-gray-500">{error}</div>
          ) : (
            candidates.map((c) => (
              <button
                key={c.id}
                onClick={() => swapMutation.mutate(c.id)}
                disabled={swapMutation.isPending}
                className="block w-full text-left px-3 py-2 hover:bg-gray-50 first:rounded-t-lg last:rounded-b-lg disabled:opacity-50 transition-colors"
              >
                <div className="text-sm font-medium text-gray-900">
                  {c.full_name || [c.first_name, c.last_name].filter(Boolean).join(" ")}
                </div>
                <div className="text-xs text-gray-500 flex items-center gap-2">
                  {c.title && <span>{c.title}</span>}
                  {c.email && <span className="truncate">{c.email}</span>}
                </div>
              </button>
            ))
          )}
          {swapMutation.isError && (
            <div className="px-3 py-2 text-xs text-red-500 border-t border-gray-100">
              {(swapMutation.error as Error).message}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
