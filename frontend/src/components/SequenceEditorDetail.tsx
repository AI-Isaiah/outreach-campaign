import { useState, useEffect } from "react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
  arrayMove,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { campaignsApi } from "../api/campaigns";
import { request } from "../api/request";
import { useToast } from "./Toast";
import { CHANNEL_LABELS } from "../constants";
import { channelBadgeClass, recalcSteps } from "../utils/sequenceUtils";

interface SequenceStep {
  id: number;
  stable_id?: string;
  step_order: number;
  channel: string;
  delay_days: number;
  template_id: number | null;
  draft_mode: string | null;
  template_subject?: string;
  template_body?: string;
}

interface Props {
  campaignId: number;
  steps: SequenceStep[];
  enrolledCount: number;
}

// ─── SortableStepRow ────────────────────────────────────────────────

function SortableStepRow({
  step,
  index,
  campaignId,
  enrolledCount,
  expandedId,
  onToggleExpand,
  onDeleted,
}: {
  step: SequenceStep;
  index: number;
  campaignId: number;
  enrolledCount: number;
  expandedId: number | null;
  onToggleExpand: (id: number) => void;
  onDeleted: () => void;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: step.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 10 : undefined,
  };

  const isExpanded = expandedId === step.id;
  const [editSubject, setEditSubject] = useState(step.template_subject || "");
  const [editBody, setEditBody] = useState(step.template_body || "");
  const [editDelay, setEditDelay] = useState(step.delay_days);
  const [editChannel, setEditChannel] = useState(step.channel);
  const [showSaveAs, setShowSaveAs] = useState(false);
  const [newTemplateName, setNewTemplateName] = useState("");

  // Sync editor fields when the step's template changes (e.g., after template dropdown selection)
  useEffect(() => {
    setEditSubject(step.template_subject || "");
    setEditBody(step.template_body || "");
  }, [step.template_id, step.template_subject, step.template_body]);

  const { toast } = useToast();
  const queryClient = useQueryClient();

  // Fetch available templates for the selector
  const { data: templates } = useQuery<{ id: number; name: string; channel: string; subject: string }[]>({
    queryKey: ["templates-list"],
    queryFn: () => request("/templates"),
    enabled: isExpanded,
    staleTime: 60_000,
  });

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!step.template_id) throw new Error("No template assigned");
      return request<{ success: boolean }>(`/templates/${step.template_id}`, {
        method: "PUT",
        body: JSON.stringify({ subject: editSubject, body_template: editBody }),
      });
    },
    onSuccess: () => {
      toast("Template saved", "success");
      queryClient.invalidateQueries({ queryKey: ["campaign-sequence", campaignId] });
      onToggleExpand(step.id);
    },
    onError: (err: Error) => {
      toast(err.message, "error");
    },
  });

  // Save as new template: create template + assign to step
  const saveAsNewMutation = useMutation({
    mutationFn: async () => {
      const result = await request<{ id: number }>("/templates", {
        method: "POST",
        body: JSON.stringify({
          name: newTemplateName,
          channel: step.channel,
          subject: editSubject,
          body_template: editBody,
        }),
      });
      // Assign new template to step
      await request(`/campaigns/${campaignId}/steps/${step.id}`, {
        method: "PATCH",
        body: JSON.stringify({ template_id: result.id }),
      });
      return result;
    },
    onSuccess: () => {
      toast("Saved as new template", "success");
      setShowSaveAs(false);
      setNewTemplateName("");
      queryClient.invalidateQueries({ queryKey: ["campaign-sequence", campaignId] });
      queryClient.invalidateQueries({ queryKey: ["templates-list"] });
      onToggleExpand(step.id);
    },
    onError: (err: Error) => toast(err.message, "error"),
  });

  // Save step properties (delay_days, channel, template_id)
  const updateStepMutation = useMutation({
    mutationFn: (updates: { delay_days?: number; channel?: string; template_id?: number }) =>
      campaignsApi.updateSequenceStep(campaignId, step.id, updates),
    onSuccess: () => {
      toast("Step updated", "success");
      queryClient.invalidateQueries({ queryKey: ["campaign-sequence", campaignId] });
    },
    onError: (err: Error) => {
      toast(err.message, "error");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => campaignsApi.deleteSequenceStep(campaignId, step.id),
    onSuccess: () => {
      toast("Step removed", "success");
      queryClient.invalidateQueries({ queryKey: ["campaign-sequence", campaignId] });
      onDeleted();
    },
    onError: (err: Error) => {
      toast(err.message, "error");
    },
  });

  const badgeClass = channelBadgeClass(step.channel);

  return (
    <div ref={setNodeRef} style={style}>
      <div
        className={`bg-white rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors px-4 py-3 ${
          isDragging ? "shadow-md" : ""
        }`}
      >
        <div className="flex items-center gap-3">
          {/* Drag handle */}
          <button
            {...attributes}
            {...listeners}
            className="text-gray-300 hover:text-gray-500 cursor-grab active:cursor-grabbing shrink-0"
            tabIndex={-1}
          >
            <GripVertical size={16} />
          </button>

          {/* Step number */}
          <span className="text-sm font-medium text-gray-900 w-14 shrink-0">
            Step {index + 1}
          </span>

          {/* Channel badge */}
          <span className={`text-xs font-medium px-2 py-0.5 rounded ${badgeClass}`}>
            {CHANNEL_LABELS[step.channel] ?? step.channel}
          </span>

          {/* Delay */}
          <span className="text-xs text-gray-400 shrink-0">
            Day {step.delay_days}
          </span>

          {/* Template name or placeholder */}
          <span className="text-sm text-gray-500 truncate flex-1 min-w-0">
            {step.template_subject || (step.template_id ? `Template #${step.template_id}` : "No template")}
          </span>

          {/* Expand/collapse — always available */}
          <button
            onClick={() => onToggleExpand(step.id)}
            className="text-gray-400 hover:text-gray-600 shrink-0"
            title={isExpanded ? "Collapse" : "Edit step"}
          >
            {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>

          {/* Delete */}
          <button
            onClick={() => deleteMutation.mutate()}
            disabled={enrolledCount > 0 || deleteMutation.isPending}
            className="text-gray-300 hover:text-red-500 transition-colors shrink-0 disabled:opacity-30 disabled:cursor-not-allowed"
            title={enrolledCount > 0 ? "Cannot delete steps while contacts are enrolled" : "Remove step"}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Expanded editing panel */}
      {isExpanded && (
        <div className="bg-gray-50 border-x border-b border-gray-100 rounded-b-lg px-5 py-4 -mt-px space-y-4">
          {/* Step properties row */}
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Channel</label>
              <select
                value={editChannel}
                onChange={(e) => {
                  setEditChannel(e.target.value);
                  updateStepMutation.mutate({ channel: e.target.value });
                }}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none bg-white"
              >
                <option value="email">Email</option>
                <option value="linkedin_connect">LinkedIn Connect</option>
                <option value="linkedin_message">LinkedIn Message</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Send on day</label>
              <input
                type="number"
                min={0}
                value={editDelay}
                onChange={(e) => setEditDelay(Number(e.target.value))}
                onBlur={() => {
                  if (editDelay !== step.delay_days) {
                    updateStepMutation.mutate({ delay_days: editDelay });
                  }
                }}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Template</label>
              <select
                value={step.template_id ?? ""}
                onChange={(e) => {
                  const tid = e.target.value ? Number(e.target.value) : undefined;
                  if (tid) updateStepMutation.mutate({ template_id: tid });
                }}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none bg-white"
              >
                <option value="">Select template...</option>
                {(templates || []).map((t) => (
                  <option key={t.id} value={t.id}>{t.name || t.subject || `Template #${t.id}`}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Template content editor (when template is assigned) */}
          {step.template_id && (
            <>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Subject</label>
                <input
                  type="text"
                  value={editSubject}
                  onChange={(e) => setEditSubject(e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                  placeholder="Email subject"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Body</label>
                <textarea
                  value={editBody}
                  onChange={(e) => setEditBody(e.target.value)}
                  rows={6}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none resize-y"
                  placeholder="Message body"
                />
              </div>
              {showSaveAs ? (
                <div className="flex gap-2 items-end">
                  <div className="flex-1">
                    <label className="block text-xs font-medium text-gray-500 mb-1">New template name</label>
                    <input
                      type="text"
                      value={newTemplateName}
                      onChange={(e) => setNewTemplateName(e.target.value)}
                      placeholder="e.g., Cold outreach v2"
                      className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                      autoFocus
                    />
                  </div>
                  <button
                    onClick={() => saveAsNewMutation.mutate()}
                    disabled={!newTemplateName.trim() || saveAsNewMutation.isPending}
                    className="px-3 py-1.5 text-xs font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
                  >
                    {saveAsNewMutation.isPending ? "Creating..." : "Create"}
                  </button>
                  <button
                    onClick={() => { setShowSaveAs(false); setNewTemplateName(""); }}
                    className="px-3 py-1.5 text-xs font-medium text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  >
                    Back
                  </button>
                </div>
              ) : (
                <div className="flex gap-2 justify-end">
                  <button
                    onClick={() => onToggleExpand(step.id)}
                    className="px-3 py-1.5 text-xs font-medium text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => setShowSaveAs(true)}
                    className="px-3 py-1.5 text-xs font-medium text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  >
                    Save as New
                  </button>
                  <button
                    onClick={() => saveMutation.mutate()}
                    disabled={saveMutation.isPending}
                    className="px-3 py-1.5 text-xs font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-800 transition-colors disabled:opacity-50"
                  >
                    {saveMutation.isPending ? "Saving..." : "Save"}
                  </button>
                </div>
              )}
            </>
          )}

          {/* No template assigned hint */}
          {!step.template_id && (
            <p className="text-xs text-gray-400">Select a template above to edit its content here.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── SequenceEditorDetail ───────────────────────────────────────────

export default function SequenceEditorDetail({ campaignId, steps, enrolledCount }: Props) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const reorderMutation = useMutation({
    mutationFn: (reordered: SequenceStep[]) =>
      campaignsApi.reorderSequence(
        campaignId,
        reordered.map((s, i) => ({
          step_id: s.id,
          step_order: i + 1,
          delay_days: s.delay_days,
          channel: s.channel,
        })),
      ),
    onSuccess: (data) => {
      toast(`Reordered ${data.affected_count} step${data.affected_count !== 1 ? "s" : ""}`, "success");
      queryClient.invalidateQueries({ queryKey: ["campaign-sequence", campaignId] });
    },
    onError: (err: Error) => {
      toast(err.message, "error");
      queryClient.invalidateQueries({ queryKey: ["campaign-sequence", campaignId] });
    },
  });

  const addMutation = useMutation({
    mutationFn: () =>
      campaignsApi.addSequenceStep(campaignId, {
        channel: "email",
        delay_days: steps.length > 0 ? steps[steps.length - 1].delay_days + 3 : 0,
        step_order: steps.length + 1,
      }),
    onSuccess: () => {
      toast("Step added", "success");
      queryClient.invalidateQueries({ queryKey: ["campaign-sequence", campaignId] });
    },
    onError: (err: Error) => {
      toast(err.message, "error");
    },
  });

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = steps.findIndex((s) => s.id === active.id);
    const newIndex = steps.findIndex((s) => s.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    const moved = arrayMove(steps, oldIndex, newIndex);
    // Recalculate delay_days + enforce linkedin_connect-first rule
    const recalced = recalcSteps(
      moved.map((s) => ({ ...s, _id: String(s.id) }))
    );
    // Map back to SequenceStep shape with recalculated values
    const reordered = recalced.map((r, i) => ({
      ...moved[i],
      step_order: r.step_order,
      delay_days: r.delay_days,
      channel: r.channel,
    }));
    reorderMutation.mutate(reordered);
  };

  const toggleExpand = (id: number) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  return (
    <div className="space-y-3">
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={steps.map((s) => s.id)}
          strategy={verticalListSortingStrategy}
        >
          <div className="space-y-2">
            {steps.map((s, i) => (
              <SortableStepRow
                key={s.id}
                step={s}
                index={i}
                campaignId={campaignId}
                enrolledCount={enrolledCount}
                expandedId={expandedId}
                onToggleExpand={toggleExpand}
                onDeleted={() => setExpandedId(null)}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>

      {/* Add step */}
      <button
        onClick={() => addMutation.mutate()}
        disabled={enrolledCount > 0 || addMutation.isPending}
        className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-600 transition-colors w-full justify-center py-3 border border-dashed border-gray-200 rounded-lg hover:border-gray-400 disabled:opacity-40 disabled:cursor-not-allowed"
        title={enrolledCount > 0 ? "Cannot add steps while contacts are enrolled" : "Add a new step"}
      >
        <Plus size={16} />
        Add step
      </button>
    </div>
  );
}
