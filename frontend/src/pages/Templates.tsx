import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Template } from "../types";

export default function Templates() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState({
    name: "",
    channel: "email",
    subject: "",
    body_template: "",
    variant_group: "",
    variant_label: "",
  });

  const { data: templates, isLoading } = useQuery({
    queryKey: ["templates"],
    queryFn: () => api.listTemplates(undefined, true),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      api.createTemplate({
        name: form.name,
        channel: form.channel,
        body_template: form.body_template,
        subject: form.subject || undefined,
        variant_group: form.variant_group || undefined,
        variant_label: form.variant_label || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      resetForm();
    },
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      api.updateTemplate(editingId!, {
        name: form.name,
        channel: form.channel,
        body_template: form.body_template,
        subject: form.subject || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      resetForm();
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: (id: number) => api.deactivateTemplate(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["templates"] }),
  });

  function resetForm() {
    setShowForm(false);
    setEditingId(null);
    setForm({ name: "", channel: "email", subject: "", body_template: "", variant_group: "", variant_label: "" });
  }

  function startEdit(t: Template) {
    setEditingId(t.id);
    setForm({
      name: t.name,
      channel: t.channel,
      subject: t.subject || "",
      body_template: t.body_template,
      variant_group: t.variant_group || "",
      variant_label: t.variant_label || "",
    });
    setShowForm(true);
  }

  const channelBadge = (ch: string) => {
    const colors: Record<string, string> = {
      email: "bg-amber-100 text-amber-800",
      linkedin_connect: "bg-blue-100 text-blue-800",
      linkedin_message: "bg-blue-100 text-blue-800",
      linkedin_engage: "bg-blue-100 text-blue-800",
      linkedin_insight: "bg-blue-100 text-blue-800",
      linkedin_final: "bg-blue-100 text-blue-800",
    };
    return colors[ch] || "bg-gray-100 text-gray-700";
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Templates</h1>
          <p className="text-gray-500 mt-1">Manage email and LinkedIn templates</p>
        </div>
        <button
          onClick={() => { resetForm(); setShowForm(true); }}
          className="px-4 py-2 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800"
        >
          New Template
        </button>
      </div>

      {/* Create/Edit form */}
      {showForm && (
        <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
          <h2 className="font-semibold text-gray-900">
            {editingId ? "Edit Template" : "New Template"}
          </h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Name</label>
              <input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                className="w-full px-3 py-2 border rounded-md text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Channel</label>
              <select
                value={form.channel}
                onChange={(e) => setForm((f) => ({ ...f, channel: e.target.value }))}
                className="w-full px-3 py-2 border rounded-md text-sm bg-white"
              >
                <option value="email">Email</option>
                <option value="linkedin_connect">LinkedIn Connect</option>
                <option value="linkedin_message">LinkedIn Message</option>
                <option value="linkedin_engage">LinkedIn Engage</option>
                <option value="linkedin_insight">LinkedIn Insight</option>
                <option value="linkedin_final">LinkedIn Final</option>
              </select>
            </div>
          </div>
          {form.channel === "email" && (
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Subject</label>
              <input
                value={form.subject}
                onChange={(e) => setForm((f) => ({ ...f, subject: e.target.value }))}
                className="w-full px-3 py-2 border rounded-md text-sm"
              />
            </div>
          )}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Body Template</label>
              <textarea
                value={form.body_template}
                onChange={(e) => setForm((f) => ({ ...f, body_template: e.target.value }))}
                className="w-full h-48 p-3 border rounded-md text-sm font-mono resize-y"
                placeholder="Hello {{ first_name }}..."
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Preview</label>
              <div className="h-48 p-3 border rounded-md bg-gray-50 text-sm overflow-y-auto whitespace-pre-wrap">
                {form.body_template
                  .replace(/\{\{\s*first_name\s*\}\}/g, "John")
                  .replace(/\{\{\s*company_name\s*\}\}/g, "Alpha Capital")
                  .replace(/\{\{\s*last_name\s*\}\}/g, "Doe")}
              </div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Variant Group</label>
              <input
                value={form.variant_group}
                onChange={(e) => setForm((f) => ({ ...f, variant_group: e.target.value }))}
                className="w-full px-3 py-2 border rounded-md text-sm"
                placeholder="e.g., subject_line"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Variant Label</label>
              <input
                value={form.variant_label}
                onChange={(e) => setForm((f) => ({ ...f, variant_label: e.target.value }))}
                className="w-full px-3 py-2 border rounded-md text-sm"
                placeholder="e.g., A"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => editingId ? updateMutation.mutate() : createMutation.mutate()}
              disabled={createMutation.isPending || updateMutation.isPending || !form.name || !form.body_template}
              className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
            >
              {editingId ? "Update" : "Create"}
            </button>
            <button
              onClick={resetForm}
              className="px-4 py-2 text-gray-600 border rounded-md text-sm hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Template list */}
      {isLoading ? (
        <p className="text-gray-400">Loading...</p>
      ) : templates && templates.length > 0 ? (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b">
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">Channel</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">Subject</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">Variant</th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {templates.map((t: Template) => (
                <tr key={t.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3 font-medium text-gray-900">{t.name}</td>
                  <td className="px-5 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${channelBadge(t.channel)}`}>
                      {t.channel}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-sm text-gray-600 truncate max-w-xs">
                    {t.subject || "-"}
                  </td>
                  <td className="px-5 py-3 text-sm text-gray-500">
                    {t.variant_group ? `${t.variant_group}/${t.variant_label}` : "-"}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <button
                      onClick={() => startEdit(t)}
                      className="text-blue-600 hover:text-blue-800 text-sm mr-3"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => deactivateMutation.mutate(t.id)}
                      className="text-red-500 hover:text-red-700 text-sm"
                    >
                      Deactivate
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-gray-400 text-center py-8">No active templates.</p>
      )}
    </div>
  );
}
