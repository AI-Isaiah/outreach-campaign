import { useFormContext } from "react-hook-form";
import Input from "../../../components/ui/Input";
import type { WizardFormData } from "../schemas/campaignSchema";

export default function StepName() {
  const { register, formState: { errors } } = useFormContext<WizardFormData>();

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Name your campaign</h2>
      <p className="text-sm text-gray-500">
        Give it a clear name so you can find it later.
      </p>
      <div>
        <Input
          label="Campaign name"
          {...register("name")}
          placeholder="e.g., Q2 Fund Allocator Outreach"
          autoFocus
          className={errors.name ? "border-red-500" : ""}
        />
        {errors.name && (
          <p className="text-sm text-red-600 mt-1">{errors.name.message}</p>
        )}
      </div>
      <div className="space-y-1">
        <label className="block text-sm font-medium text-gray-700">
          Description (optional)
        </label>
        <textarea
          className={`w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none transition-colors duration-150 ${
            errors.description ? "border-red-500" : "border-gray-200"
          }`}
          rows={3}
          {...register("description")}
          placeholder="What's this campaign about?"
        />
        {errors.description && (
          <p className="text-sm text-red-600 mt-1">{errors.description.message}</p>
        )}
      </div>
    </div>
  );
}
