import { useDroppable } from "@dnd-kit/core";
import type { Deal } from "../../types";
import DraggableDealCard from "./DealCard";
import type { StageConfig } from "./types";

export default function StageColumn({
  stage,
  deals,
  onAddDeal,
  onClickDeal,
}: {
  stage: StageConfig;
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
