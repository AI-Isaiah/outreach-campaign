import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  DragOverlay,
  closestCorners,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
} from "@dnd-kit/core";
import { Kanban } from "lucide-react";
import { api } from "../api/client";
import type { Deal, DealPipeline } from "../types";
import { SkeletonCard } from "../components/Skeleton";
import EmptyState from "../components/EmptyState";
import ErrorCard from "../components/ui/ErrorCard";
import { DealCardContent } from "../components/pipeline/DealCard";
import StageColumn from "../components/pipeline/StageColumn";
import DealDetailPanel from "../components/pipeline/DealDetailPanel";
import AddDealModal from "../components/pipeline/AddDealModal";
import type { StageConfig } from "../components/pipeline/types";

const STAGES: readonly StageConfig[] = [
  { key: "cold", label: "Cold", color: "bg-gray-50 border-gray-300", dot: "bg-gray-400" },
  { key: "contacted", label: "Contacted", color: "bg-blue-50 border-blue-300", dot: "bg-blue-400" },
  { key: "engaged", label: "Engaged", color: "bg-indigo-50 border-indigo-300", dot: "bg-indigo-400" },
  { key: "meeting_booked", label: "Meeting Booked", color: "bg-amber-50 border-amber-300", dot: "bg-amber-400" },
  { key: "negotiating", label: "Negotiating", color: "bg-purple-50 border-purple-300", dot: "bg-purple-400" },
  { key: "won", label: "Won", color: "bg-emerald-50 border-emerald-300", dot: "bg-emerald-400" },
  { key: "lost", label: "Lost", color: "bg-red-50 border-red-300", dot: "bg-red-400" },
] as const;

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
          stages={STAGES}
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
          stages={STAGES}
          onClose={() => setSelectedDeal(null)}
          onDelete={(id) => deleteMutation.mutate(id)}
        />
      )}
    </div>
  );
}
