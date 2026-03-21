import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { LIFECYCLE_STAGES } from "../constants";

const LIFECYCLE_OPTIONS = LIFECYCLE_STAGES.map((s) => ({
  value: s,
  label: s.charAt(0).toUpperCase() + s.slice(1),
}));

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function CreateContactModal({ open, onClose }: Props) {
  const queryClient = useQueryClient();

  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    phone_number: "",
    linkedin_url: "",
    title: "",
    company_id: "" as string | number,
    lifecycle_stage: "cold",
    newsletter_opt_in: false,
    notes: "",
  });

  const { data: companies } = useQuery({
    queryKey: ["companies-select"],
    queryFn: () => api.listCompanies({ per_page: 500 }),
    enabled: open,
  });

  const mutation = useMutation({
    mutationFn: () =>
      api.createContact({
        first_name: form.first_name,
        last_name: form.last_name,
        email: form.email || undefined,
        phone_number: form.phone_number || undefined,
        linkedin_url: form.linkedin_url || undefined,
        title: form.title || undefined,
        company_id: form.company_id ? Number(form.company_id) : undefined,
        lifecycle_stage: form.lifecycle_stage,
        newsletter_opt_in: form.newsletter_opt_in,
        notes: form.notes || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["crm-contacts"] });
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
      onClose();
      setForm({
        first_name: "", last_name: "", email: "", phone_number: "",
        linkedin_url: "", title: "", company_id: "",
        lifecycle_stage: "cold", newsletter_opt_in: false, notes: "",
      });
    },
  });

  if (!open) return null;

  const handleField = (field: string, value: string | boolean) =>
    setForm((f) => ({ ...f, [field]: value }));

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Add Contact</h2>
        </div>

        <div className="px-6 py-4 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                First Name *
              </label>
              <input
                type="text"
                value={form.first_name}
                onChange={(e) => handleField("first_name", e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Last Name *
              </label>
              <input
                type="text"
                value={form.last_name}
                onChange={(e) => handleField("last_name", e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
            <input
              type="email"
              value={form.email}
              onChange={(e) => handleField("email", e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Phone</label>
            <input
              type="text"
              value={form.phone_number}
              onChange={(e) => handleField("phone_number", e.target.value)}
              placeholder="+1 555 123 4567"
              className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">LinkedIn URL</label>
            <input
              type="url"
              value={form.linkedin_url}
              onChange={(e) => handleField("linkedin_url", e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Title</label>
            <input
              type="text"
              value={form.title}
              onChange={(e) => handleField("title", e.target.value)}
              placeholder="e.g. CIO, Portfolio Manager"
              className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Company</label>
            <select
              value={form.company_id}
              onChange={(e) => handleField("company_id", e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm bg-white"
            >
              <option value="">No company</option>
              {companies?.companies?.map((c: any) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Lifecycle Stage</label>
            <select
              value={form.lifecycle_stage}
              onChange={(e) => handleField("lifecycle_stage", e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm bg-white"
            >
              {LIFECYCLE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.newsletter_opt_in}
              onChange={(e) => handleField("newsletter_opt_in", e.target.checked)}
              className="rounded border-gray-300"
            />
            <span className="text-gray-700">Subscribe to newsletter</span>
          </label>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Notes</label>
            <textarea
              value={form.notes}
              onChange={(e) => handleField("notes", e.target.value)}
              rows={3}
              className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={!form.first_name || !form.last_name || mutation.isPending}
            className="px-4 py-2 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 disabled:opacity-50"
          >
            {mutation.isPending ? "Creating..." : "Add Contact"}
          </button>
        </div>

        {mutation.isError && (
          <div className="px-6 pb-4">
            <p className="text-sm text-red-600">{(mutation.error as Error).message}</p>
          </div>
        )}
      </div>
    </div>
  );
}
