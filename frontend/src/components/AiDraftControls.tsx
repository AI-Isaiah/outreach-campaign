import { useState } from "react";
import { Sparkles, RefreshCw, Loader2 } from "lucide-react";
import type { UseMutationResult } from "@tanstack/react-query";

interface AiDraftControlsProps {
  hasAiDraft: boolean;
  draftMode?: "template" | "ai";
  hasResearch?: boolean;
  generateMutation: UseMutationResult<unknown, Error, void, unknown>;
}

/**
 * Shared AI draft controls for queue cards (email + LinkedIn).
 * Shows: AI-drafted label + regenerate, generate button, or AI-ready indicator.
 */
export default function AiDraftControls({
  hasAiDraft,
  draftMode,
  hasResearch,
  generateMutation,
}: AiDraftControlsProps) {
  const [showConfirm, setShowConfirm] = useState(false);

  if (hasAiDraft) {
    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs text-purple-600 font-medium">
            <Sparkles size={12} className="text-purple-500" />
            AI-drafted from research
          </div>
          <button
            onClick={() => setShowConfirm(true)}
            disabled={generateMutation.isPending}
            aria-busy={generateMutation.isPending}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs text-gray-500 hover:text-purple-600 rounded border border-gray-200 hover:border-purple-300 transition-colors"
          >
            {generateMutation.isPending ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <RefreshCw size={12} />
            )}
            {generateMutation.isPending ? "Generating..." : "Regenerate"}
          </button>
        </div>
        {showConfirm && (
          <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-md px-3 py-2 text-sm">
            <span className="text-amber-800">Regenerate will replace your edits.</span>
            <button
              onClick={() => { generateMutation.mutate(); setShowConfirm(false); }}
              className="px-2 py-0.5 bg-purple-600 text-white rounded text-xs font-medium hover:bg-purple-700"
            >
              Confirm
            </button>
            <button
              onClick={() => setShowConfirm(false)}
              className="px-2 py-0.5 bg-white border border-gray-200 text-gray-600 rounded text-xs font-medium hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    );
  }

  if (hasResearch) {
    return (
      <div>
        {draftMode === "ai" && (
          <div className="flex items-center gap-1.5 text-xs mb-2">
            <Sparkles size={12} className="text-purple-500" />
            <span className="text-purple-600 font-medium">AI-ready</span>
            <span className="text-gray-400">Research available</span>
          </div>
        )}
        <button
          onClick={() => generateMutation.mutate()}
          disabled={generateMutation.isPending}
          aria-label="Generate AI-personalized draft using research data"
          aria-busy={generateMutation.isPending}
          className="inline-flex items-center gap-1.5 bg-white border border-purple-300 text-purple-700 hover:bg-purple-50 px-3 py-1.5 rounded-md text-sm font-medium transition-colors disabled:opacity-50 sm:w-auto w-full justify-center"
        >
          {generateMutation.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Sparkles size={14} />
          )}
          {generateMutation.isPending ? "Generating..." : "Generate AI Draft"}
        </button>
        {generateMutation.isError && (
          <span className="text-red-500 text-sm mt-1 block">
            {(generateMutation.error as Error).message || "Generation failed"}
          </span>
        )}
      </div>
    );
  }

  return null;
}
