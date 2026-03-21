import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Mail, MessageCircle, StickyNote } from "lucide-react";
import { api } from "../api/client";
import type { InboxItem } from "../types";
import { SkeletonCard } from "../components/Skeleton";
import EmptyState from "../components/EmptyState";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";

const CHANNEL_TABS = [
  { key: undefined, label: "All" },
  { key: "email", label: "Email" },
  { key: "whatsapp", label: "WhatsApp" },
  { key: "notes", label: "Notes" },
] as const;

const CHANNEL_STYLES: Record<string, string> = {
  email: "bg-blue-100 text-blue-700",
  whatsapp: "bg-green-100 text-green-700",
  note: "bg-gray-100 text-gray-700",
};

const CHANNEL_ICONS: Record<string, React.ReactNode> = {
  email: <Mail size={14} />,
  whatsapp: <MessageCircle size={14} />,
  note: <StickyNote size={14} />,
};

export default function Inbox() {
  const [channel, setChannel] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["inbox", channel, page],
    queryFn: () => api.getInbox({ channel, page }),
  });

  const items = data?.items || [];
  const totalPages = data?.pages || 1;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Inbox</h1>
        <p className="text-sm text-gray-500 mt-1">
          {data?.total || 0} messages across all channels
        </p>
      </div>

      {/* Channel tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit">
        {CHANNEL_TABS.map((tab) => (
          <button
            key={tab.label}
            onClick={() => {
              setChannel(tab.key);
              setPage(1);
            }}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
              channel === tab.key
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {/* Error */}
      {isError && (
        <ErrorCard
          message={(error as Error).message}
          onRetry={() => refetch()}
        />
      )}

      {/* Items */}
      {!isLoading && items.length > 0 ? (
        <>
          <div className="space-y-2">
            {items.map((item: InboxItem, idx: number) => (
              <Link
                key={`${item.channel}-${item.item_id}-${idx}`}
                to={`/contacts/${item.contact_id}`}
                className="block bg-white rounded-xl border border-gray-200 p-4 hover:border-gray-300 hover:shadow-sm transition-all"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                          CHANNEL_STYLES[item.channel] || CHANNEL_STYLES.note
                        }`}
                      >
                        {CHANNEL_ICONS[item.channel] || CHANNEL_ICONS.note}
                        {item.channel}
                      </span>
                      {item.classification && item.channel === "email" && (
                        <span className="text-xs text-gray-400">
                          {item.classification}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm text-gray-900">
                        {item.contact_name || "Unknown"}
                      </span>
                      {item.company_name && (
                        <span className="text-xs text-gray-400">
                          {item.company_name}
                        </span>
                      )}
                    </div>
                    {item.subject && (
                      <div className="text-sm text-gray-700 mt-0.5 truncate">
                        {item.subject}
                      </div>
                    )}
                    {item.body && (
                      <div className="text-sm text-gray-500 mt-0.5 truncate">
                        {item.body.slice(0, 120)}
                        {item.body.length > 120 ? "..." : ""}
                      </div>
                    )}
                  </div>
                  <span className="text-xs text-gray-400 whitespace-nowrap shrink-0">
                    {new Date(item.occurred_at).toLocaleDateString()}
                  </span>
                </div>
              </Link>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Page {page} of {totalPages}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                >
                  Previous
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </>
      ) : (
        !isLoading && !isError && (
          <EmptyState
            icon={<Mail size={40} />}
            title="Inbox zero"
            description="No messages to review"
          />
        )
      )}
    </div>
  );
}
