import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import QueueTabContent from "../QueueTabContent";

// ── Mock queueApi ───────────────────────────────────────────────────
const mockGetQueue = vi.fn();
vi.mock("../../../api/queue", () => ({
  queueApi: {
    getQueue: (...args: unknown[]) => mockGetQueue(...args),
  },
}));

// ── Mock child cards to keep tests focused on the tab logic ─────────
vi.mock("../../QueueEmailCard", () => ({
  default: ({ item }: { item: { contact_name: string } }) => (
    <div data-testid="email-card">{item.contact_name}</div>
  ),
}));
vi.mock("../../QueueLinkedInCard", () => ({
  default: ({ item }: { item: { contact_name: string } }) => (
    <div data-testid="linkedin-card">{item.contact_name}</div>
  ),
}));

// Stub localStorage for jsdom environments where it may not be defined
const localStorageStore: Record<string, string> = {};
Object.defineProperty(globalThis, "localStorage", {
  value: {
    getItem: (key: string) => localStorageStore[key] ?? null,
    setItem: (key: string, val: string) => { localStorageStore[key] = val; },
    removeItem: (key: string) => { delete localStorageStore[key]; },
  },
  writable: true,
});

function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  mockGetQueue.mockReset();
  delete localStorageStore["queue_keyboard_hint_seen_count"];
});

describe("QueueTabContent — scope parameter", () => {
  it("passes scope='all' to the API when 'All Queued' is selected (default)", async () => {
    mockGetQueue.mockResolvedValue({ items: [], total_enrolled: 0 });

    renderWithClient(<QueueTabContent campaignName="test_campaign" />);

    // Wait for query to fire and component to render past loading state
    await screen.findByText("All Queued");

    // The default state is "all" — verify the API received scope: "all", NOT undefined
    const [campaign, options] = mockGetQueue.mock.calls[0];
    expect(campaign).toBe("test_campaign");
    expect(options).toBeDefined();
    expect(options.scope).toBe("all");
  });

  it("passes scope='today' to the API when 'Due today' pill is clicked", async () => {
    mockGetQueue.mockResolvedValue({ items: [], total_enrolled: 0 });
    const user = userEvent.setup();

    renderWithClient(<QueueTabContent campaignName="test_campaign" />);

    // Wait for the pills to appear (past loading state)
    const todayPill = await screen.findByText(/Due today/);

    mockGetQueue.mockClear();
    await user.click(todayPill);

    await waitFor(() => {
      expect(mockGetQueue).toHaveBeenCalled();
    });

    const [, options] = mockGetQueue.mock.calls[0];
    expect(options.scope).toBe("today");
  });

  it("passes scope='overdue' to the API when 'Overdue' pill is clicked", async () => {
    mockGetQueue.mockResolvedValue({ items: [], total_enrolled: 0 });
    const user = userEvent.setup();

    renderWithClient(<QueueTabContent campaignName="test_campaign" />);

    // Wait for the pills to appear (past loading state)
    const overduePill = await screen.findByText("Overdue");

    mockGetQueue.mockClear();
    await user.click(overduePill);

    await waitFor(() => {
      expect(mockGetQueue).toHaveBeenCalled();
    });

    const [, options] = mockGetQueue.mock.calls[0];
    expect(options.scope).toBe("overdue");
  });
});
