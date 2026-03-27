import { useRef, useEffect, useMemo } from "react";
import Button from "./ui/Button";
import type { QueueItem } from "../types";

interface QueueBatchHeaderProps {
  items: QueueItem[];
  approvedIds: Set<number>;
  onToggleAll: () => void;
  onSelectCampaign: (campaignName: string) => void;
  onDeselectAll: () => void;
}

export default function QueueBatchHeader({
  items,
  approvedIds,
  onToggleAll,
  onSelectCampaign,
  onDeselectAll,
}: QueueBatchHeaderProps) {
  const checkboxRef = useRef<HTMLInputElement>(null);

  const visibleIds = useMemo(
    () => new Set(items.map((i) => i.contact_id)),
    [items],
  );

  const selectedCount = useMemo(
    () => [...approvedIds].filter((id) => visibleIds.has(id)).length,
    [approvedIds, visibleIds],
  );

  const allSelected = items.length > 0 && selectedCount === items.length;
  const someSelected = selectedCount > 0 && !allSelected;

  // Keep the indeterminate property in sync -- it is not controllable via JSX
  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = someSelected;
    }
  }, [someSelected]);

  const campaignNames = useMemo(() => {
    const names = new Set<string>();
    for (const item of items) {
      if (item.campaign_name) names.add(item.campaign_name);
    }
    return [...names].sort();
  }, [items]);

  if (items.length === 0) return null;

  return (
    <div className="bg-gray-50 border-b border-gray-200 px-5 py-3 flex items-center justify-between rounded-t-lg">
      {/* Left: checkbox + selected count */}
      <div className="flex items-center gap-3">
        <input
          ref={checkboxRef}
          type="checkbox"
          checked={allSelected}
          onChange={onToggleAll}
          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 h-4 w-4 cursor-pointer"
          aria-label={`Select all ${items.length} items`}
        />
        {selectedCount > 0 && (
          <span className="text-sm font-medium text-blue-600">
            {selectedCount} selected
          </span>
        )}
      </div>

      {/* Right: campaign pills + deselect link */}
      <div className="flex items-center gap-2">
        {campaignNames.map((name) => (
          <Button
            key={name}
            variant="secondary"
            size="sm"
            onClick={() => onSelectCampaign(name)}
          >
            {name}
          </Button>
        ))}

        {selectedCount > 0 && (
          <>
            {campaignNames.length > 0 && (
              <div className="w-px h-4 bg-gray-200 mx-1" />
            )}
            <button
              type="button"
              onClick={onDeselectAll}
              className="text-sm font-medium text-gray-500 hover:text-gray-700 transition-colors focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 rounded"
            >
              Deselect All
            </button>
          </>
        )}
      </div>
    </div>
  );
}
