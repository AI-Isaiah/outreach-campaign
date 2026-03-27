import { useEffect, useRef } from "react";
import { useFormContext } from "react-hook-form";
import {
  Check,
  Mail,
  Linkedin,
  GripVertical,
  Plus,
  Trash2,
} from "lucide-react";
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
import { CHANNEL_LABELS } from "../../../constants";
import type { GeneratedStep } from "../../../api/campaigns";
import type { WizardFormData, SequenceFormData } from "../schemas/campaignSchema";

type ChannelValue = SequenceFormData["channels"][number];

// ─── Constants ─────────────────────────────────────────────────────

const TOUCHPOINT_OPTIONS = [
  { value: 3, label: "Quick", desc: "3 touchpoints" },
  { value: 5, label: "Standard", desc: "5 touchpoints" },
  { value: 7, label: "Thorough", desc: "7 touchpoints" },
];

const WIZARD_CHANNELS = ["email", "linkedin_connect", "linkedin_message"] as const;
const CHANNEL_OPTIONS = WIZARD_CHANNELS.map((ch) => ({
  value: ch,
  label: CHANNEL_LABELS[ch] ?? ch,
}));

function channelBadgeClass(ch: string): string {
  return ch === "email" ? "bg-blue-100 text-blue-700" : "bg-indigo-100 text-indigo-700";
}

// ─── Sequence generation ───────────────────────────────────────────

export function generateLocalSequence(touchpoints: number, channels: string[]): GeneratedStep[] {
  const steps: GeneratedStep[] = [];
  const hasEmail = channels.includes("email");
  const hasLinkedin = channels.includes("linkedin");
  const isSingleChannel = channels.length === 1;

  let linkedinConnectUsed = false; // only one connect allowed per sequence

  for (let i = 0; i < touchpoints; i++) {
    let channel: string;
    let delay: number;

    if (isSingleChannel) {
      if (channels[0] === "linkedin") {
        channel = !linkedinConnectUsed ? "linkedin_connect" : "linkedin_message";
        linkedinConnectUsed = true;
      } else {
        channel = "email";
      }
      // Increasing gaps for single channel
      if (i === 0) delay = 0;
      else if (i <= 2) delay = steps[i - 1].delay_days + 3 + i;
      else delay = steps[i - 1].delay_days + 4 + i;
    } else {
      // Alternate email and linkedin
      const isEmail = i % 2 === 0 ? hasEmail : !hasEmail;
      if (isEmail) {
        channel = "email";
      } else {
        channel = !linkedinConnectUsed ? "linkedin_connect" : "linkedin_message";
        linkedinConnectUsed = true;
      }

      if (i === 0) delay = 0;
      else {
        const prevChannel = steps[i - 1].channel;
        const sameType = (channel === "email" && prevChannel === "email") ||
          (channel !== "email" && prevChannel !== "email");
        const minGap = sameType ? 3 : 2;
        const backoff = Math.floor(i / 3);
        delay = steps[i - 1].delay_days + minGap + backoff;
      }
    }

    steps.push({
      _id: crypto.randomUUID(),
      step_order: i + 1,
      channel,
      delay_days: delay,
      template_id: null,
    });
  }

  return steps;
}

// ─── Helpers ───────────────────────────────────────────────────────

/** Recalculate step_order (1-indexed) and delay_days after reorder/edit. */
function recalcSteps(steps: GeneratedStep[]): GeneratedStep[] {
  // Ensure the first LinkedIn step is always linkedin_connect
  const hasConnect = steps.some((s) => s.channel === "linkedin_connect");
  if (!hasConnect) {
    const firstLinkedInIdx = steps.findIndex((s) =>
      s.channel === "linkedin_message" || s.channel === "linkedin_engage" || s.channel === "linkedin_insight"
    );
    if (firstLinkedInIdx !== -1) {
      steps = steps.map((s, i) =>
        i === firstLinkedInIdx ? { ...s, channel: "linkedin_connect" } : s
      );
    }
  }

  return steps.map((s, i) => {
    let delay: number;
    if (i === 0) {
      delay = 0;
    } else {
      const prev = steps[i - 1];
      const sameType =
        (s.channel === "email" && prev.channel === "email") ||
        (s.channel !== "email" && prev.channel !== "email");
      const minGap = sameType ? 3 : 2;
      const backoff = Math.floor(i / 3);
      delay = prev.delay_days + minGap + backoff;
    }
    return {
      ...s,
      step_order: i + 1,
      delay_days: delay,
    };
  });
}

// ─── SortableStep sub-component ────────────────────────────────────

/** Single sortable step row in the sequence editor. */
function SortableStep({
  step,
  index,
  totalSteps,
  hasLinkedInConnect,
  onChangeChannel,
  onDelete,
}: {
  step: GeneratedStep;
  index: number;
  totalSteps: number;
  hasLinkedInConnect: boolean;
  onChangeChannel: (channel: string) => void;
  onDelete: () => void;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: step._id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`flex items-center gap-3 py-2.5 px-2 rounded-lg ${
        isDragging ? "bg-white shadow-md" : "hover:bg-white/60"
      } ${index < totalSteps - 1 ? "border-b border-gray-100" : ""}`}
    >
      {/* Drag handle */}
      <button
        {...attributes}
        {...listeners}
        className="text-gray-300 hover:text-gray-500 cursor-grab active:cursor-grabbing shrink-0"
        tabIndex={-1}
      >
        <GripVertical size={16} />
      </button>

      {/* Day */}
      <span className="text-xs text-gray-400 w-14 shrink-0">
        Day {step.delay_days}
      </span>

      {/* Channel selector */}
      <select
        value={step.channel}
        onChange={(e) => onChangeChannel(e.target.value)}
        className={`text-xs font-medium px-2 py-1 rounded border-0 cursor-pointer ${channelBadgeClass(step.channel)}`}
      >
        {CHANNEL_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Step number */}
      <span className="text-xs text-gray-500 flex-1">
        Step {index + 1}
      </span>

      {/* Delete */}
      {totalSteps > 1 && (
        <button
          onClick={onDelete}
          className="text-gray-300 hover:text-red-500 transition-colors shrink-0"
          title="Remove step"
        >
          <Trash2 size={14} />
        </button>
      )}
    </div>
  );
}

// ─── StepSequence main component ───────────────────────────────────

export default function StepSequence() {
  const { watch, setValue, formState: { errors } } = useFormContext<WizardFormData>();

  const touchpoints = watch("touchpoints");
  const channels = watch("channels");
  const steps = watch("steps");

  // Track previous touchpoints/channels to detect user-driven changes
  const prevTouchpointsRef = useRef(touchpoints);
  const prevChannelsRef = useRef(channels);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  // Convert channels array to Set for toggle logic
  const channelsSet = new Set(channels);

  // Auto-regenerate steps when touchpoints or channels change
  useEffect(() => {
    const touchpointsChanged = prevTouchpointsRef.current !== touchpoints;
    const channelsChanged =
      prevChannelsRef.current.length !== channels.length ||
      prevChannelsRef.current.some((c, i) => c !== channels[i]);

    prevTouchpointsRef.current = touchpoints;
    prevChannelsRef.current = channels;

    // Also generate on first mount when steps are empty
    if (!touchpointsChanged && !channelsChanged && steps.length > 0) return;

    if (channels.length === 0) {
      setValue("steps", [], { shouldValidate: true });
      return;
    }

    const generated = generateLocalSequence(touchpoints, channels);
    setValue("steps", generated, { shouldValidate: true });
  }, [touchpoints, channels, setValue]);

  const hasLinkedInConnect = steps.some((s) => s.channel === "linkedin_connect");

  const toggleChannel = (key: ChannelValue) => {
    const updated = new Set<ChannelValue>(channelsSet);
    if (updated.has(key)) {
      if (updated.size <= 1) return; // Prevent removing last channel
      updated.delete(key);
    } else {
      updated.add(key);
    }
    setValue("channels", Array.from(updated), { shouldValidate: true });
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = steps.findIndex((s) => s._id === active.id);
    const newIndex = steps.findIndex((s) => s._id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    const reordered = arrayMove(steps, oldIndex, newIndex);
    setValue("steps", recalcSteps(reordered), { shouldValidate: true });
  };

  const handleChangeChannel = (index: number, channel: string) => {
    let updated = [...steps];

    if (channel === "linkedin_connect") {
      const existingIdx = updated.findIndex(
        (s, i) => i !== index && s.channel === "linkedin_connect"
      );
      if (existingIdx !== -1) {
        // Swap the existing linkedin_connect:
        // If new position is BEFORE old -> old becomes linkedin_message (connect already happened)
        // If new position is AFTER old -> old becomes email (connect hasn't happened yet at that point)
        updated[existingIdx] = {
          ...updated[existingIdx],
          channel: index < existingIdx ? "linkedin_message" : "email",
        };
      }
    }

    updated[index] = { ...updated[index], channel };
    setValue("steps", recalcSteps(updated), { shouldValidate: true });
  };

  const handleDelete = (index: number) => {
    const updated = steps.filter((_, i) => i !== index);
    setValue("steps", recalcSteps(updated), { shouldValidate: true });
  };

  const handleAdd = () => {
    // Default to email, or linkedin_message if no email channel
    const defaultChannel = channelsSet.has("email") ? "email" : "linkedin_message";
    const lastDelay = steps.length > 0 ? steps[steps.length - 1].delay_days : 0;
    const newStep: GeneratedStep = {
      _id: crypto.randomUUID(),
      step_order: steps.length + 1,
      channel: defaultChannel,
      delay_days: lastDelay + 3,
      template_id: null,
    };
    setValue("steps", recalcSteps([...steps, newStep]), { shouldValidate: true });
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Build your sequence</h2>
        <p className="text-sm text-gray-500 mt-1">
          Generate a starting sequence, then drag to reorder and customize.
        </p>
      </div>

      {/* Touchpoint selector */}
      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-3">Start with a template</h3>
        <div className="grid grid-cols-3 gap-3">
          {TOUCHPOINT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`border-2 rounded-lg p-4 text-center transition-colors ${
                touchpoints === opt.value
                  ? "border-gray-900 bg-gray-50"
                  : "border-gray-200 hover:border-gray-300"
              }`}
              onClick={() => setValue("touchpoints", opt.value)}
            >
              <div className="text-2xl font-bold">{opt.value}</div>
              <div className="text-xs text-gray-500 mt-1">{opt.label}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Channel toggles */}
      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-3">Which channels?</h3>
        <div className="flex gap-3">
          {([
            { key: "email" as ChannelValue, label: "Email", icon: Mail },
            { key: "linkedin" as ChannelValue, label: "LinkedIn", icon: Linkedin },
          ]).map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              className={`flex items-center gap-2 px-4 py-2 rounded-full border-2 text-sm font-medium transition-colors ${
                channelsSet.has(key)
                  ? "border-gray-900 bg-gray-900 text-white"
                  : "border-gray-200 text-gray-500 hover:border-gray-300"
              }`}
              onClick={() => toggleChannel(key)}
            >
              {channelsSet.has(key) && <Check size={14} />}
              <Icon size={14} />
              {label}
            </button>
          ))}
        </div>
        {errors.channels && (
          <p className="text-sm text-red-600 mt-1">
            {typeof errors.channels.message === "string"
              ? errors.channels.message
              : (errors.channels.root?.message ?? "Invalid channel selection")}
          </p>
        )}
      </div>

      {/* Sequence editor */}
      {steps.length > 0 && (
        <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Sequence &mdash; drag to reorder
          </h4>

          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={steps.map((s) => s._id)}
              strategy={verticalListSortingStrategy}
            >
              <div className="space-y-0">
                {steps.map((s, i) => (
                  <SortableStep
                    key={s._id}
                    step={s}
                    index={i}
                    totalSteps={steps.length}
                    hasLinkedInConnect={hasLinkedInConnect}
                    onChangeChannel={(ch) => handleChangeChannel(i, ch)}
                    onDelete={() => handleDelete(i)}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>

          {/* Add step button */}
          <button
            type="button"
            onClick={handleAdd}
            className="mt-3 flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors w-full justify-center py-2 border border-dashed border-gray-200 rounded-lg hover:border-gray-400"
          >
            <Plus size={14} />
            Add step
          </button>
        </div>
      )}

      {/* Steps validation error */}
      {errors.steps && (
        <p className="text-sm text-red-600">
          {typeof errors.steps.message === "string"
            ? errors.steps.message
            : (errors.steps.root?.message ?? "At least 1 sequence step required")}
        </p>
      )}
    </div>
  );
}
