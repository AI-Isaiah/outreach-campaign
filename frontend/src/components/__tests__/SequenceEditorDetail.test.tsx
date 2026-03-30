import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SequenceEditorDetail from "../SequenceEditorDetail";
import type { SequenceStep } from "../SequenceEditorDetail";

// ── Track invalidateQueries calls ───────────────────────────────────
let invalidateSpy: ReturnType<typeof vi.fn>;
let testQueryClient: QueryClient;

// ── Mock campaignsApi ───────────────────────────────────────────────
vi.mock("../../api/campaigns", () => ({
  campaignsApi: {
    updateSequenceStep: vi.fn().mockResolvedValue({}),
    deleteSequenceStep: vi.fn().mockResolvedValue({}),
    addSequenceStep: vi.fn().mockResolvedValue({}),
    reorderSequence: vi.fn().mockResolvedValue({ affected_count: 0 }),
  },
}));

// ── Mock request for template save (PUT /templates/:id) ─────────────
const mockRequest = vi.fn();
vi.mock("../../api/request", () => ({
  request: (...args: unknown[]) => mockRequest(...args),
}));

// ── Mock Toast ──────────────────────────────────────────────────────
vi.mock("../Toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

// ── Mock dnd-kit (no drag behavior needed) ──────────────────────────
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  closestCenter: vi.fn(),
  PointerSensor: vi.fn(),
  KeyboardSensor: vi.fn(),
  useSensor: vi.fn(),
  useSensors: () => [],
}));
vi.mock("@dnd-kit/sortable", () => ({
  SortableContext: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  sortableKeyboardCoordinates: vi.fn(),
  useSortable: () => ({
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
    transform: null,
    transition: null,
    isDragging: false,
  }),
  verticalListSortingStrategy: vi.fn(),
  arrayMove: (arr: unknown[]) => arr,
}));
vi.mock("@dnd-kit/utilities", () => ({
  CSS: { Transform: { toString: () => undefined } },
}));

// ── Mock sequenceUtils ──────────────────────────────────────────────
vi.mock("../../utils/sequenceUtils", () => ({
  channelBadgeClass: () => "bg-gray-100 text-gray-700",
  recalcSteps: (s: unknown[]) => s,
}));

// ── Mock constants ──────────────────────────────────────────────────
vi.mock("../../constants", () => ({
  CHANNEL_LABELS: { email: "Email", linkedin_connect: "LinkedIn Connect", linkedin_message: "LinkedIn Message" },
}));

const makeStep = (overrides: Partial<SequenceStep> = {}): SequenceStep => ({
  id: 1,
  stable_id: "abc-123",
  step_order: 1,
  channel: "email",
  delay_days: 0,
  template_id: 42,
  draft_mode: null,
  template_subject: "Test Subject",
  template_body: "Hello {{ first_name }}",
  ...overrides,
});

function renderEditor(steps: SequenceStep[] = [makeStep()]) {
  testQueryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  invalidateSpy = vi.spyOn(testQueryClient, "invalidateQueries");

  return render(
    <QueryClientProvider client={testQueryClient}>
      <SequenceEditorDetail campaignId={1} steps={steps} enrolledCount={0} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockRequest.mockReset();
});

describe("SequenceEditorDetail — cache invalidation on template save", () => {
  it("invalidates queue-all cache after saving a template", async () => {
    mockRequest
      // First call: GET /templates (template list for selector)
      .mockResolvedValueOnce([{ id: 42, name: "Test Template", channel: "email", subject: "Test" }])
      // Second call: PUT /templates/42 (save)
      .mockResolvedValueOnce({ success: true });

    const user = userEvent.setup();
    renderEditor();

    // Expand the step
    const expandBtn = screen.getByTitle("Edit step");
    await user.click(expandBtn);

    // Click Save button
    const saveBtn = await screen.findByText("Save");
    await user.click(saveBtn);

    await waitFor(() => {
      // Verify that invalidateQueries was called with the queue-all key
      const queueInvalidations = invalidateSpy.mock.calls.filter(
        ([opts]: [{ queryKey: string[] }]) =>
          opts.queryKey &&
          JSON.stringify(opts.queryKey) === JSON.stringify(["queue-all"]),
      );
      expect(queueInvalidations.length).toBeGreaterThan(0);
    });
  });
});
