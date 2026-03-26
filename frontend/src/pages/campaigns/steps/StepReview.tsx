import { useFormContext } from "react-hook-form";
import type { WizardFormData } from "../schemas/campaignSchema";

export default function StepReview() {
  const { getValues } = useFormContext<WizardFormData>();
  const { name, description, crmSelectedIds, csvContacts, contactSource, steps, channels } = getValues();

  const contactCount = contactSource === "crm"
    ? crmSelectedIds.length
    : csvContacts.filter(c => c.selected).length;
  const totalDays = steps.length > 0 ? steps[steps.length - 1].delay_days : 0;

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Review & Launch</h2>

      <div className="bg-gray-50 rounded-lg p-4 space-y-3">
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">Campaign</span>
          <span className="font-medium">{name}</span>
        </div>
        {description && (
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">Description</span>
            <span className="text-gray-700">{description}</span>
          </div>
        )}
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">Contacts</span>
          <span className="font-medium">{contactCount}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">Steps</span>
          <span className="font-medium">{steps.length} over {totalDays} days</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">Channels</span>
          <span className="font-medium">{channels.join(", ")}</span>
        </div>
      </div>

      <p className="text-xs text-gray-400">
        Click "Launch Campaign" to start, or "Save as Draft" to launch later.
      </p>
    </div>
  );
}
