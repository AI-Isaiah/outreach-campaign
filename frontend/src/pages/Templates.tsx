import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileText, Plus, Sparkles } from "lucide-react";
import { api } from "../api/client";
import type { Template } from "../types";
import { SkeletonTable } from "../components/Skeleton";
import EmptyState from "../components/EmptyState";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import Input from "../components/ui/Input";
import Select from "../components/ui/Select";
import { channelBadgeClass } from "../utils/sequenceUtils";

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

  const { data: templates, isLoading, isError, error: templatesError, refetch } = useQuery({
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
    mutationFn: () => {
      if (!editingId) throw new Error("No template selected for editing");
      return api.updateTemplate(editingId, {
        name: form.name,
        channel: form.channel,
        body_template: form.body_template,
        subject: form.subject || undefined,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      resetForm();
    },
  });

  const aiGenerateMutation = useMutation({
    mutationFn: () =>
      api.improveMessage({
        channel: form.channel,
        body: form.body_template || "",
        subject: form.subject || undefined,
        instruction: form.body_template
          ? "Improve this outreach template. Make it concise, personal, and compelling for crypto fund allocators. Keep Jinja2 variables like {{ first_name }}."
          : `Write a ${form.channel === "email" ? "cold email" : "LinkedIn connection"} outreach template for crypto fund allocators. Use Jinja2 variables: {{ first_name }}, {{ company_name }}, {{ calendly_url }}. Be concise and personal.`,
      }),
    onSuccess: (result) => {
      setForm((f) => ({
        ...f,
        body_template: result.body,
        subject: result.subject || f.subject,
      }));
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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Templates</h1>
          <p className="text-sm text-gray-500 mt-1">Manage email and LinkedIn templates</p>
        </div>
        <div className="flex items-center gap-3">
          <Link to="/campaigns/wizard?step=2">
            <Button
              variant="secondary"
              size="md"
              leftIcon={<Sparkles size={16} />}
            >
              Generate Sequence
            </Button>
          </Link>
          <Button
            variant="primary"
            size="md"
            leftIcon={<Plus size={16} />}
            onClick={() => { resetForm(); setShowForm(true); }}
          >
            New Template
          </Button>
        </div>
      </div>

      {/* Create/Edit form */}
      {showForm && (
        <Card>
          <Link to="/templates" onClick={resetForm} className="text-sm text-gray-400 hover:text-gray-600 inline-flex items-center gap-1 mb-3">
            <ArrowLeft size={14} /> Templates
          </Link>
          <h2 className="font-semibold text-gray-900 mb-4">
            {editingId ? "Edit Template" : "New Template"}
          </h2>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="Name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
              <Select
                label="Channel"
                value={form.channel}
                onChange={(e) => setForm((f) => ({ ...f, channel: e.target.value }))}
              >
                <option value="email">Email</option>
                <option value="linkedin_connect">LinkedIn Connect</option>
                <option value="linkedin_message">LinkedIn Message</option>
                <option value="linkedin_engage">LinkedIn Engage</option>
                <option value="linkedin_insight">LinkedIn Insight</option>
                <option value="linkedin_final">LinkedIn Final</option>
              </Select>
            </div>
            {form.channel === "email" && (
              <Input
                label="Subject"
                value={form.subject}
                onChange={(e) => setForm((f) => ({ ...f, subject: e.target.value }))}
              />
            )}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <label className="block text-sm font-medium text-gray-700">Body Template</label>
                  <Button
                    variant="ghost"
                    size="sm"
                    leftIcon={<Sparkles size={14} />}
                    onClick={() => aiGenerateMutation.mutate()}
                    loading={aiGenerateMutation.isPending}
                  >
                    {form.body_template ? "Improve with AI" : "Generate with AI"}
                  </Button>
                </div>
                {aiGenerateMutation.isError && (
                  <p className="text-xs text-red-600">{(aiGenerateMutation.error as Error).message}</p>
                )}
                <textarea
                  value={form.body_template}
                  onChange={(e) => setForm((f) => ({ ...f, body_template: e.target.value }))}
                  className="w-full h-48 p-3 border border-gray-200 rounded-lg text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Hello {{ first_name }}..."
                />
              </div>
              <div className="space-y-1">
                <label className="block text-sm font-medium text-gray-700">Preview</label>
                <div className="h-48 p-3 border border-gray-200 rounded-lg bg-gray-50 text-sm overflow-y-auto whitespace-pre-wrap">
                  {form.body_template
                    .replace(/\{\{\s*first_name\s*\}\}/g, "John")
                    .replace(/\{\{\s*company_name\s*\}\}/g, "Alpha Capital")
                    .replace(/\{\{\s*last_name\s*\}\}/g, "Doe")}
                </div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="Variant Group"
                value={form.variant_group}
                onChange={(e) => setForm((f) => ({ ...f, variant_group: e.target.value }))}
                placeholder="e.g., subject_line"
              />
              <Input
                label="Variant Label"
                value={form.variant_label}
                onChange={(e) => setForm((f) => ({ ...f, variant_label: e.target.value }))}
                placeholder="e.g., A"
              />
            </div>
            <div className="flex gap-2">
              <Button
                variant="accent"
                size="md"
                onClick={() => editingId ? updateMutation.mutate() : createMutation.mutate()}
                disabled={!form.name || !form.body_template}
                loading={createMutation.isPending || updateMutation.isPending}
              >
                {editingId ? "Update" : "Create"}
              </Button>
              <Button variant="secondary" size="md" onClick={resetForm}>
                Cancel
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Template list */}
      {isError && (
        <ErrorCard
          message={(templatesError as Error).message}
          onRetry={() => refetch()}
        />
      )}

      {isLoading ? (
        <SkeletonTable rows={5} cols={5} />
      ) : templates && templates.length > 0 ? (
        <Card padding="none">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide max-w-[180px]">Name</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide w-24">Channel</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide min-w-[280px]">Subject</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Variant</th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {templates.map((t: Template) => (
                <tr key={t.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-5 py-3 font-medium text-gray-900">{t.name}</td>
                  <td className="px-5 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${channelBadgeClass(t.channel)}`}>
                      {t.channel}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-sm text-gray-600 truncate max-w-xs" title={t.subject || ""}>
                    {t.subject || "-"}
                  </td>
                  <td className="px-5 py-3 text-sm text-gray-500">
                    {t.variant_group ? `${t.variant_group}/${t.variant_label}` : "-"}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <button
                      onClick={() => startEdit(t)}
                      className="text-blue-600 hover:text-blue-800 text-sm font-medium mr-3"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => deactivateMutation.mutate(t.id)}
                      className="text-red-500 hover:text-red-700 text-sm font-medium"
                    >
                      Deactivate
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : (
        !isLoading && !isError && (
          <EmptyState
            icon={<FileText size={40} />}
            title="No active templates"
            description="Create a template to use in your campaigns"
          />
        )
      )}
    </div>
  );
}
