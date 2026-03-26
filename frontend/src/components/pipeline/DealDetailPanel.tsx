import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { Deal } from "../../types";
import type { StageConfig } from "./types";

function formatAum(aum: number | null | undefined): string | null {
  if (!aum) return null;
  return aum >= 1000 ? `$${(aum / 1000).toFixed(1)}B` : `$${aum.toLocaleString()}M`;
}

export default function DealDetailPanel({
  deal,
  stages,
  onClose,
  onDelete,
}: {
  deal: Deal;
  stages: readonly StageConfig[];
  onClose: () => void;
  onDelete: (id: number) => void;
}) {
  const { data: detail } = useQuery({
    queryKey: ["deal", deal.id],
    queryFn: () => api.getDeal(deal.id),
  });

  const stageLabel = stages.find((s) => s.key === deal.stage)?.label || deal.stage;
  const aum = formatAum(deal.aum_millions);
  const history = detail?.stage_history || [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative w-96 bg-white shadow-xl border-l overflow-y-auto">
        <div className="sticky top-0 bg-white border-b px-4 py-3 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900 truncate">{deal.title}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">
            &times;
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* Stage badge */}
          <div>
            <div className="text-xs text-gray-500 uppercase tracking-wide">Stage</div>
            <span className="inline-block mt-1 text-sm font-medium bg-gray-100 px-2 py-1 rounded">
              {stageLabel}
            </span>
          </div>

          {/* Company */}
          <div>
            <div className="text-xs text-gray-500 uppercase tracking-wide">Company</div>
            <div className="text-sm text-gray-900 mt-1">{deal.company_name}</div>
            {aum && <div className="text-xs text-gray-500">AUM: {aum}</div>}
          </div>

          {/* Contact */}
          {deal.contact_name && (
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide">Contact</div>
              <div className="text-sm text-gray-900 mt-1">{deal.contact_name}</div>
              {deal.contact_email && (
                <div className="text-xs text-gray-500">{deal.contact_email}</div>
              )}
            </div>
          )}

          {/* Amount */}
          {deal.amount_millions != null && (
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide">Deal Amount</div>
              <div className="text-sm font-medium text-emerald-700 mt-1">
                ${deal.amount_millions}M
              </div>
            </div>
          )}

          {/* Expected close */}
          {deal.expected_close_date && (
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide">Expected Close</div>
              <div className="text-sm text-gray-900 mt-1">{deal.expected_close_date}</div>
            </div>
          )}

          {/* Notes */}
          {deal.notes && (
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide">Notes</div>
              <p className="text-sm text-gray-700 mt-1 whitespace-pre-wrap">{deal.notes}</p>
            </div>
          )}

          {/* Stage history */}
          {history.length > 0 && (
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">
                Stage History
              </div>
              <div className="space-y-2">
                {history.map((h) => {
                  const fromLabel =
                    stages.find((s) => s.key === h.from_stage)?.label || h.from_stage || "\u2014";
                  const toLabel =
                    stages.find((s) => s.key === h.to_stage)?.label || h.to_stage;
                  return (
                    <div key={h.id} className="flex items-center gap-2 text-xs text-gray-600">
                      <span className="text-gray-400">
                        {new Date(h.changed_at).toLocaleDateString()}
                      </span>
                      <span>
                        {fromLabel} &rarr; {toLabel}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Delete */}
          <div className="pt-4 border-t">
            <button
              onClick={() => {
                if (confirm("Delete this deal?")) onDelete(deal.id);
              }}
              className="text-sm text-red-600 hover:text-red-800"
            >
              Delete deal
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
