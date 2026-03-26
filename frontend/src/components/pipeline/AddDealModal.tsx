import { useState } from "react";
import type { Company } from "../../types";
import Button from "../ui/Button";
import type { StageConfig } from "./types";

export default function AddDealModal({
  stage,
  stages,
  companies,
  onClose,
  onSubmit,
  isSubmitting,
}: {
  stage: string;
  stages: readonly StageConfig[];
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

  const stageLabel = stages.find((s) => s.key === stage)?.label || stage;

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
