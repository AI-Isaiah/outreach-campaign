import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { PendingReply } from "../types";

const CLASSIFICATION_COLORS: Record<string, string> = {
  positive: "bg-emerald-100 text-emerald-800",
  negative: "bg-red-100 text-red-800",
  neutral: "bg-gray-100 text-gray-700",
};

function PendingReplyCard({ reply }: { reply: PendingReply }) {
  const queryClient = useQueryClient();

  const confirmMutation = useMutation({
    mutationFn: (outcome: string) => api.confirmReply(reply.id, outcome),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pending-replies"] });
    },
  });

  const classColor =
    CLASSIFICATION_COLORS[reply.classification || ""] || "bg-gray-100 text-gray-700";

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <div className="flex items-start justify-between mb-2">
        <div>
          <Link
            to={`/contacts/${reply.contact_id}`}
            className="font-semibold text-gray-900 hover:text-blue-600"
          >
            {reply.contact_name}
          </Link>
          {reply.company_name && (
            <span className="text-gray-500 ml-2 text-sm">
              {reply.company_name}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {reply.classification && (
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${classColor}`}>
              {reply.classification}
            </span>
          )}
          {reply.confidence != null && (
            <span className="text-xs text-gray-400">
              {(reply.confidence * 100).toFixed(0)}%
            </span>
          )}
        </div>
      </div>

      {reply.subject && (
        <div className="text-sm text-gray-700 font-medium mb-1">
          {reply.subject}
        </div>
      )}
      {reply.snippet && (
        <p className="text-sm text-gray-500 mb-3 line-clamp-2">
          {reply.snippet}
        </p>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => confirmMutation.mutate("replied_positive")}
          disabled={confirmMutation.isPending}
          className="px-3 py-1.5 bg-emerald-600 text-white rounded text-xs font-medium hover:bg-emerald-700 disabled:opacity-50"
        >
          Positive
        </button>
        <button
          onClick={() => confirmMutation.mutate("replied_negative")}
          disabled={confirmMutation.isPending}
          className="px-3 py-1.5 bg-red-600 text-white rounded text-xs font-medium hover:bg-red-700 disabled:opacity-50"
        >
          Negative
        </button>
        <button
          onClick={() => confirmMutation.mutate("neutral")}
          disabled={confirmMutation.isPending}
          className="px-3 py-1.5 bg-gray-200 text-gray-700 rounded text-xs font-medium hover:bg-gray-300 disabled:opacity-50"
        >
          Neutral
        </button>
        {confirmMutation.isError && (
          <span className="text-red-500 text-xs self-center">
            {(confirmMutation.error as Error).message}
          </span>
        )}
      </div>
    </div>
  );
}

export default React.memo(PendingReplyCard);
