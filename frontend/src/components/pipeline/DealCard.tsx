import { useRef } from "react";
import { useDraggable } from "@dnd-kit/core";
import type { Deal } from "../../types";

function formatAum(aum: number | null | undefined): string | null {
  if (!aum) return null;
  return aum >= 1000 ? `$${(aum / 1000).toFixed(1)}B` : `$${aum.toLocaleString()}M`;
}

export function DealCardContent({ deal }: { deal: Deal }) {
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

export default function DraggableDealCard({
  deal,
  onClick,
}: {
  deal: Deal;
  onClick: () => void;
}) {
  const wasDragging = useRef(false);
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: deal.id,
  });

  // Track when a drag occurs so we can suppress the subsequent click
  if (isDragging) {
    wasDragging.current = true;
  }

  const style = transform
    ? { transform: `translate(${transform.x}px, ${transform.y}px)` }
    : undefined;

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      onClick={() => {
        if (wasDragging.current) {
          wasDragging.current = false;
          return;
        }
        onClick();
      }}
      className={`bg-white rounded-md border border-gray-200 p-3 shadow-sm cursor-grab active:cursor-grabbing hover:shadow-md transition-shadow select-none ${
        isDragging ? "opacity-50" : ""
      }`}
    >
      <DealCardContent deal={deal} />
    </div>
  );
}
