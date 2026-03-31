import { useCallback } from "react";
import { Mail, Linkedin } from "lucide-react";
import type { QueueItem } from "../../types";
import QueueEmailCard from "../../components/QueueEmailCard";
import QueueLinkedInCard from "../../components/QueueLinkedInCard";

interface CardSectionProps {
  emailItems: QueueItem[];
  linkedinItems: QueueItem[];
  focusedIndex: number;
  selectedIds: Set<number>;
  onToggle: (contactId: number) => void;
  onDeferred: () => void;
  setCardRef: (index: number, el: HTMLDivElement | null) => void;
}

export default function CardSection({
  emailItems,
  linkedinItems,
  focusedIndex,
  selectedIds,
  onToggle,
  onDeferred,
  setCardRef,
}: CardSectionProps) {
  return (
    <>
      {/* Email section */}
      {emailItems.length > 0 && (
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            <Mail size={16} className="text-amber-600" />
            Email ({emailItems.length})
          </h2>
          <div className="space-y-3">
            {emailItems.map((item, i) => (
              <div key={`${item.contact_id}-email`} ref={(el) => setCardRef(i, el)}>
                <QueueEmailCard
                  item={item}
                  campaign={item.campaign_name || ""}
                  onDeferred={onDeferred}
                  isFocused={focusedIndex === i}
                  isSelected={selectedIds.has(item.contact_id)}
                  onToggle={onToggle}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* LinkedIn section */}
      {linkedinItems.length > 0 && (
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            <Linkedin size={16} className="text-blue-600" />
            LinkedIn ({linkedinItems.length})
          </h2>
          <div className="space-y-3">
            {linkedinItems.map((item, i) => {
              const flatIdx = emailItems.length + i;
              return (
                <div key={`${item.contact_id}-li`} ref={(el) => setCardRef(flatIdx, el)}>
                  <QueueLinkedInCard
                    item={item}
                    campaign={item.campaign_name || ""}
                    onDeferred={onDeferred}
                    isFocused={focusedIndex === flatIdx}
                    isSelected={selectedIds.has(item.contact_id)}
                    onToggle={onToggle}
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}
