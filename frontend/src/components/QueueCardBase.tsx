import React from "react";
import { Pencil, CheckCircle } from "lucide-react";
import type { QueueItem } from "../types";
import AumTierBadge from "./AumTierBadge";
import SignalBadge from "./SignalBadge";
import ContactEditPanel from "./ContactEditPanel";
import SkipMenu from "./SkipMenu";
import SwapMenu from "./SwapMenu";
import type { ContactEditState } from "../hooks/useContactEdit";

export interface QueueCardBaseProps {
  item: QueueItem;
  campaign: string;
  isFocused?: boolean;
  isApproved?: boolean;
  isSelected?: boolean;
  onToggle?: (id: number) => void;
  headerIcon: React.ReactNode;
  headerBg: string;
  headerBorder: string;
  children: React.ReactNode;
}

/** Internal props added by the card implementations */
export interface QueueCardBaseInternalProps extends QueueCardBaseProps {
  contactEdit: ContactEditState;
  skipMutation: { mutate: (reason: string) => void; isPending: boolean };
  stepColor: string;
  headerRight?: React.ReactNode;
}

function QueueCardBaseSkipped({ contactName }: { contactName: string }) {
  return (
    <div className="bg-gray-50 border border-gray-200 rounded-lg p-5">
      <div className="flex items-center gap-2">
        <span className="text-gray-400 text-lg">&#8594;</span>
        <span className="font-medium text-gray-500">
          {contactName} &mdash; Skipped (back tomorrow)
        </span>
      </div>
    </div>
  );
}

function QueueCardBase({
  item,
  isFocused,
  isApproved,
  isSelected,
  onToggle,
  headerIcon,
  headerBg,
  headerBorder,
  contactEdit,
  skipMutation,
  stepColor,
  headerRight,
  children,
}: QueueCardBaseInternalProps) {
  return (
    <div
      className={`bg-white border rounded-lg shadow-sm overflow-hidden ${
        isFocused ? "ring-2 ring-blue-500 ring-offset-2 border-blue-300" : "border-gray-200"
      } ${isSelected ? "border-l-4 border-l-blue-500 bg-blue-50/30" : ""}`}
      aria-label={`${item.channel.startsWith("linkedin") ? "LinkedIn" : "Email"}: ${item.contact_name}`}
    >
      <div className={`${headerBg} px-5 py-3 flex items-center justify-between border-b ${headerBorder}`}>
        <div className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={isSelected}
            onChange={(e) => { e.stopPropagation(); onToggle?.(item.contact_id); }}
            className="w-4 h-4 accent-blue-600 flex-shrink-0 cursor-pointer"
            aria-label={`Select ${item.contact_name}`}
          />
          {isApproved && <CheckCircle size={16} className="text-green-500 flex-shrink-0" />}
          {headerIcon}
          <span className="font-semibold text-gray-900">
            {item.contact_name}
          </span>
          <button
            onClick={() => contactEdit.setShowEdit(!contactEdit.showEdit)}
            className="p-0.5 text-gray-400 hover:text-gray-600 transition-colors"
            title="Edit contact details"
            aria-label="Edit contact details"
            data-role="edit-contact"
          >
            <Pencil size={14} />
          </button>
          <span className="text-gray-500 mx-1">&middot;</span>
          <span className="text-gray-600">
            {item.company_name}
            {item.firm_type && (
              <span className="text-gray-400 text-sm ml-1">({item.firm_type})</span>
            )}
          </span>
          <AumTierBadge tier={item.aum_tier} />
          {item.fund_signals && item.fund_signals.length > 0 && (
            <SignalBadge signals={item.fund_signals} />
          )}
        </div>
        <div className="flex items-center gap-3">
          {headerRight}
          <span className={`text-sm ${stepColor} font-medium`}>
            Step {item.step_order}/{item.total_steps}
          </span>
          {item.step_order === 1 && item.campaign_id && (
            <SwapMenu contactId={item.contact_id} campaignId={item.campaign_id} />
          )}
          <SkipMenu onSkip={(reason) => skipMutation.mutate(reason)} isPending={skipMutation.isPending} />
        </div>
      </div>

      <ContactEditPanel edit={contactEdit} />

      {children}
    </div>
  );
}

export { QueueCardBaseSkipped };
export default React.memo(QueueCardBase);
