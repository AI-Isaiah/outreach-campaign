import { useState } from "react";
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
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { campaignsApi } from "../api/campaigns";
import { request } from "../api/request";
import { useToast } from "./Toast";
import { CHANNEL_LABELS } from "../constants";
import { channelBadgeClass } from "../utils/sequenceUtils";

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

  const { toast } = useToast();
  const queryClient = useQueryClient();

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
            {step.delay_days === 0 ? "Day 0" : `Day ${step.delay_days}`}
          </span>

          {/* Template name or placeholder */}
          <span className="text-sm text-gray-500 truncate flex-1 min-w-0">
            {step.template_subject || (step.template_id ? `Template #${step.template_id}` : "No template")}
          </span>

          {/* Expand/collapse */}
          {step.template_id && (
            <button
              onClick={() => onToggleExpand(step.id)}
              className="text-gray-400 hover:text-gray-600 shrink-0"
              title={isExpanded ? "Collapse" : "Edit template"}
            >
              {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
          )}

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
      {isExpanded && step.template_id && (
        <div className="bg-gray-50 border-x border-b border-gray-100 rounded-b-lg px-5 py-4 -mt-px space-y-3">
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
          <div className="flex gap-2 justify-end">
            <button
              onClick={() => onToggleExpand(step.id)}
              className="px-3 py-1.5 text-xs font-medium text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              className="px-3 py-1.5 text-xs font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-800 transition-colors disabled:opacity-50"
            >
              {saveMutation.isPending ? "Saving..." : "Save"}
            </button>
          </div>
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
        reordered.map((s, i) => ({ step_id: s.id, step_order: i + 1 })),
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

    const reordered = arrayMove(steps, oldIndex, newIndex);
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
