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
  if (hasAiDraft) {
    return (
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs text-purple-600 font-medium">
          <Sparkles size={12} className="text-purple-500" />
          AI-drafted from research
        </div>
        <button
          onClick={() => {
            if (confirm("Regenerate will replace your edits. Continue?")) {
              generateMutation.mutate();
            }
          }}
          disabled={generateMutation.isPending}
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
