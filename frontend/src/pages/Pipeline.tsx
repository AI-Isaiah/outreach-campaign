import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  DragOverlay,
  closestCorners,
  PointerSensor,
  useSensor,
  useSensors,
  useDraggable,
  useDroppable,
  type DragStartEvent,
  type DragEndEvent,
} from "@dnd-kit/core";
import { Kanban } from "lucide-react";
import { api } from "../api/client";
import type { Deal, DealPipeline, Company } from "../types";
import { SkeletonCard } from "../components/Skeleton";
import EmptyState from "../components/EmptyState";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";

const STAGES = [
  { key: "cold", label: "Cold", color: "bg-gray-50 border-gray-300", dot: "bg-gray-400" },
  { key: "contacted", label: "Contacted", color: "bg-blue-50 border-blue-300", dot: "bg-blue-400" },
  { key: "engaged", label: "Engaged", color: "bg-indigo-50 border-indigo-300", dot: "bg-indigo-400" },
  { key: "meeting_booked", label: "Meeting Booked", color: "bg-amber-50 border-amber-300", dot: "bg-amber-400" },
  { key: "negotiating", label: "Negotiating", color: "bg-purple-50 border-purple-300", dot: "bg-purple-400" },
  { key: "won", label: "Won", color: "bg-emerald-50 border-emerald-300", dot: "bg-emerald-400" },
  { key: "lost", label: "Lost", color: "bg-red-50 border-red-300", dot: "bg-red-400" },
] as const;

function formatAum(aum: number | null | undefined): string | null {
  if (!aum) return null;
  return aum >= 1000 ? `$${(aum / 1000).toFixed(1)}B` : `$${aum.toLocaleString()}M`;
}

/* ---- Draggable deal card ---- */
function DraggableDealCard({
  deal,
  onClick,
}: {
  deal: Deal;
  onClick: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: deal.id,
  });

  const style = transform
    ? { transform: `translate(${transform.x}px, ${transform.y}px)` }
    : undefined;

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      onClick={(e) => {
        // Don't open detail if dragging
        if (!isDragging) onClick();
      }}
      className={`bg-white rounded-md border border-gray-200 p-3 shadow-sm cursor-grab active:cursor-grabbing hover:shadow-md transition-shadow select-none ${
        isDragging ? "opacity-50" : ""
      }`}
    >
      <DealCardContent deal={deal} />
    </div>
  );
}

/* ---- Static card content (shared between draggable + overlay) ---- */
function DealCardContent({ deal }: { deal: Deal }) {
  const aum = formatAum(deal.aum_millions);
  return (
    <>
      <div className="font-medium text-sm text-gray-900 truncate">{deal.title}</div>
      <div className="text-xs text-gray-500 mt-1 truncate">{deal.company_name}</div>
      {deal.contact_name && (
        <div className="text-xs text-gray-400 truncate">{deal.contact_name}</div>
      )}
      <div className="flex items-center gap-2 mt-2">
        {aum && (
          <span className="text-xs font-medium text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded">
            {aum}
          </span>
        )}
        {deal.amount_millions != null && (
          <span className="text-xs font-medium text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded">
            ${deal.amount_millions}M
          </span>
        )}
      </div>
    </>
  );
}

/* ---- Stage column (droppable) ---- */
function StageColumn({
  stage,
  deals,
  onAddDeal,
  onClickDeal,
}: {
  stage: (typeof STAGES)[number];
  deals: Deal[];
  onAddDeal: (stage: string) => void;
  onClickDeal: (deal: Deal) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: stage.key });

  const totalAum = deals.reduce((sum, d) => sum + (d.amount_millions || 0), 0);

  return (
    <div
      ref={setNodeRef}
      className={`flex flex-col w-64 shrink-0 rounded-lg border-2 transition-colors ${stage.color} ${
        isOver ? "ring-2 ring-blue-400 border-blue-400" : ""
      }`}
    >
      {/* Header */}
      <div className="px-3 py-2 border-b border-gray-200/60">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${stage.dot}`} />
            <span className="text-sm font-semibold text-gray-700">{stage.label}</span>
            <span className="text-xs text-gray-400 bg-white/80 px-1.5 py-0.5 rounded-full">
              {deals.length}
            </span>
          </div>
          <button
            onClick={() => onAddDeal(stage.key)}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none w-6 h-6 flex items-center justify-center rounded hover:bg-white/60"
            title={`Add deal to ${stage.label}`}
          >
            +
          </button>
        </div>
        {totalAum > 0 && (
          <div className="text-xs text-gray-400 mt-1">${totalAum.toLocaleString()}M total</div>
        )}
      </div>

      {/* Cards */}
      <div className="p-2 space-y-2 flex-1 min-h-[80px] overflow-y-auto max-h-[calc(100vh-280px)]">
        {deals.map((deal) => (
          <DraggableDealCard
            key={deal.id}
            deal={deal}
            onClick={() => onClickDeal(deal)}
          />
        ))}
      </div>
    </div>
  );
}

/* ---- Deal detail slide-out ---- */
function DealDetailPanel({
  deal,
  onClose,
  onDelete,
}: {
  deal: Deal;
  onClose: () => void;
  onDelete: (id: number) => void;
}) {
  const { data: detail } = useQuery({
    queryKey: ["deal", deal.id],
    queryFn: () => api.getDeal(deal.id),
  });

  const stageLabel = STAGES.find((s) => s.key === deal.stage)?.label || deal.stage;
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
                    STAGES.find((s) => s.key === h.from_stage)?.label || h.from_stage || "—";
                  const toLabel =
                    STAGES.find((s) => s.key === h.to_stage)?.label || h.to_stage;
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

/* ---- Add deal modal ---- */
function AddDealModal({
  stage,
  companies,
  onClose,
  onSubmit,
  isSubmitting,
}: {
  stage: string;
  companies: Company[];
  onClose: () => void;
  onSubmit: (data: {
    company_id: number;
    title: string;
    stage: string;
    amount_millions?: number;
    notes?: string;
  }) => void;
  isSubmitting: boolean;
}) {
  const [title, setTitle] = useState("");
  const [companyId, setCompanyId] = useState("");
  const [amount, setAmount] = useState("");
  const [notes, setNotes] = useState("");

  const stageLabel = STAGES.find((s) => s.key === stage)?.label || stage;

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-[28rem] space-y-4">
        <h2 className="text-lg font-semibold">Add Deal to {stageLabel}</h2>

        <div className="space-y-3">
          <input
            type="text"
            placeholder="Deal title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full px-3 py-2 border rounded-md text-sm"
            autoFocus
          />

          <select
            value={companyId}
            onChange={(e) => setCompanyId(e.target.value)}
            className="w-full px-3 py-2 border rounded-md text-sm bg-white"
          >
            <option value="">Select company...</option>
            {companies.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
                {c.aum_millions ? ` ($${c.aum_millions}M)` : ""}
              </option>
            ))}
          </select>

          <input
            type="number"
            placeholder="Deal amount ($M) — optional"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-full px-3 py-2 border rounded-md text-sm"
            step="0.1"
            min="0"
          />

          <textarea
            placeholder="Notes — optional"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-full px-3 py-2 border rounded-md text-sm resize-none"
            rows={2}
          />
        </div>

        <div className="flex gap-2 justify-end pt-2">
          <Button variant="ghost" size="md" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="md"
            onClick={() =>
              onSubmit({
                company_id: Number(companyId),
                title,
                stage,
                amount_millions: amount ? Number(amount) : undefined,
                notes: notes || undefined,
              })
            }
            disabled={!title || !companyId}
            loading={isSubmitting}
          >
            Create
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ---- Main component ---- */
export default function Pipeline() {
  const queryClient = useQueryClient();
  const [activeDeal, setActiveDeal] = useState<Deal | null>(null);
  const [selectedDeal, setSelectedDeal] = useState<Deal | null>(null);
  const [showForm, setShowForm] = useState<string | null>(null);
  const [dragError, setDragError] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  const { data, isLoading, error: pipelineError, refetch } = useQuery({
    queryKey: ["pipeline"],
    queryFn: () => api.getDealPipeline(),
  });

  const { data: companiesData } = useQuery({
    queryKey: ["companies-for-deals"],
    queryFn: () => api.listCompanies(),
    enabled: showForm !== null,
  });

  const stageMutation = useMutation({
    mutationFn: ({ id, stage }: { id: number; stage: string }) =>
      api.updateDealStage(id, stage),
    onMutate: async ({ id, stage: newStage }) => {
      setDragError(null);
      await queryClient.cancelQueries({ queryKey: ["pipeline"] });
      const prev = queryClient.getQueryData<DealPipeline>(["pipeline"]);

      // Optimistic update
      if (prev) {
        const next: DealPipeline = { pipeline: {} };
        let movedDeal: Deal | undefined;

        for (const [stage, deals] of Object.entries(prev.pipeline)) {
          const found = deals.find((d) => d.id === id);
          if (found) {
            movedDeal = { ...found, stage: newStage };
            next.pipeline[stage] = deals.filter((d) => d.id !== id);
          } else {
            next.pipeline[stage] = [...deals];
          }
        }

        if (movedDeal) {
          if (!next.pipeline[newStage]) next.pipeline[newStage] = [];
          next.pipeline[newStage].unshift(movedDeal);
        }

        queryClient.setQueryData(["pipeline"], next);
      }

      return { prev };
    },
    onError: (err, _vars, context) => {
      if (context?.prev) queryClient.setQueryData(["pipeline"], context.prev);
      setDragError((err as Error).message || "Failed to update deal stage");
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["pipeline"] }),
  });

  const createMutation = useMutation({
    mutationFn: (data: {
      company_id: number;
      title: string;
      stage: string;
      amount_millions?: number;
      notes?: string;
    }) => api.createDeal(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
      setShowForm(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteDeal(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
      setSelectedDeal(null);
    },
  });

  const pipeline = data?.pipeline || {};

  // Summary stats
  const allDeals = Object.values(pipeline).flat();
  const activeDeals = allDeals.filter((d) => d.stage !== "won" && d.stage !== "lost");
  const totalActiveAmount = activeDeals.reduce((s, d) => s + (d.amount_millions || 0), 0);
  const wonDeals = pipeline["won"] || [];
  const totalWonAmount = wonDeals.reduce((s: number, d: Deal) => s + (d.amount_millions || 0), 0);

  function handleDragStart(event: DragStartEvent) {
    const dealId = Number(event.active.id);
    for (const deals of Object.values(pipeline)) {
      const found = (deals as Deal[]).find((d) => d.id === dealId);
      if (found) {
        setActiveDeal(found);
        break;
      }
    }
  }

  function handleDragEnd(event: DragEndEvent) {
    setActiveDeal(null);
    const { active, over } = event;
    if (!over) return;

    const dealId = Number(active.id);
    const newStage = String(over.id);

    // Find current stage and only mutate if stage changed
    for (const [stage, deals] of Object.entries(pipeline)) {
      if ((deals as Deal[]).some((d) => d.id === dealId) && stage !== newStage) {
        stageMutation.mutate({ id: dealId, stage: newStage });
        break;
      }
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 bg-gray-200 rounded animate-pulse" />
        <div className="flex gap-3 overflow-x-auto pb-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="w-64 shrink-0">
              <SkeletonCard />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (pipelineError) {
    return (
      <ErrorCard
        message={(pipelineError as Error).message}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* Error message */}
      {dragError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm flex items-center justify-between">
          <span>{dragError}</span>
          <button
            onClick={() => setDragError(null)}
            className="text-red-600 hover:text-red-800 font-medium"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Header + summary */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Pipeline</h1>
          <p className="text-gray-500 text-sm mt-1">
            Drag deals between stages to update status
          </p>
        </div>
        <div className="flex gap-4 text-sm">
          <div className="text-center">
            <div className="text-lg font-semibold text-gray-900">{allDeals.length}</div>
            <div className="text-xs text-gray-500">Total</div>
          </div>
          <div className="text-center">
            <div className="text-lg font-semibold text-gray-900">{activeDeals.length}</div>
            <div className="text-xs text-gray-500">Active</div>
          </div>
          {totalActiveAmount > 0 && (
            <div className="text-center">
              <div className="text-lg font-semibold text-gray-900">
                ${totalActiveAmount.toLocaleString()}M
              </div>
              <div className="text-xs text-gray-500">In Pipeline</div>
            </div>
          )}
          {totalWonAmount > 0 && (
            <div className="text-center">
              <div className="text-lg font-semibold text-emerald-600">
                ${totalWonAmount.toLocaleString()}M
              </div>
              <div className="text-xs text-gray-500">Won</div>
            </div>
          )}
        </div>
      </div>

      {/* Empty state */}
      {allDeals.length === 0 && (
        <EmptyState
          icon={<Kanban size={40} />}
          title="No active deals"
          description="Create a deal to get started"
        />
      )}

      {/* Kanban board */}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div className="flex gap-3 overflow-x-auto pb-4">
          {STAGES.map((stage) => (
            <StageColumn
              key={stage.key}
              stage={stage}
              deals={(pipeline[stage.key] || []) as Deal[]}
              onAddDeal={(s) => setShowForm(s)}
              onClickDeal={(d) => setSelectedDeal(d)}
            />
          ))}
        </div>

        <DragOverlay dropAnimation={null}>
          {activeDeal ? (
            <div className="bg-white rounded-md border border-blue-300 p-3 shadow-lg w-60 rotate-2">
              <DealCardContent deal={activeDeal} />
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>

      {/* Add deal modal */}
      {showForm && (
        <AddDealModal
          stage={showForm}
          companies={companiesData?.companies || []}
          onClose={() => setShowForm(null)}
          onSubmit={(data) => createMutation.mutate(data)}
          isSubmitting={createMutation.isPending}
        />
      )}

      {/* Deal detail slide-out */}
      {selectedDeal && (
        <DealDetailPanel
          deal={selectedDeal}
          onClose={() => setSelectedDeal(null)}
          onDelete={(id) => deleteMutation.mutate(id)}
        />
      )}
    </div>
  );
}
