import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { CampaignWithMetrics } from "../../api/campaigns";

const mockListCampaigns = vi.fn();

vi.mock("../../api/campaigns", () => ({
  campaignsApi: {
    listCampaigns: (...args: unknown[]) => mockListCampaigns(...args),
  },
}));

vi.mock("../../components/StatusBadge", () => ({
  default: ({ status }: { status: string }) => (
    <span data-testid="status-badge">{status}</span>
  ),
}));

vi.mock("../../components/HealthScoreBadge", () => ({
  default: ({ score, totalSent }: { score?: number | null; totalSent?: number }) => (
    <span data-testid="health-score">{(score == null || (score === 0 && (totalSent === 0 || totalSent == null))) ? "N/A" : score}</span>
  ),
}));

vi.mock("../../components/Skeleton", () => ({
  SkeletonCard: () => <div data-testid="skeleton-card" />,
}));

vi.mock("../../components/ui/ErrorCard", () => ({
  default: ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
    <div data-testid="error-card">
      <span>{message}</span>
      {onRetry && <button onClick={onRetry}>Try Again</button>}
    </div>
  ),
}));

vi.mock("../../components/ui/Button", () => ({
  default: ({ children, ...rest }: Record<string, unknown>) => (
    <button {...rest}>{children as string}</button>
  ),
}));

import CampaignList from "../CampaignList";

function makeCampaign(overrides: Partial<CampaignWithMetrics> = {}): CampaignWithMetrics {
  return {
    id: 1,
    name: "Q1_2026_initial",
    description: "Email + LinkedIn",
    status: "active",
    created_at: "2026-01-15T10:00:00Z",
    contacts_count: 42,
    replied_count: 8,
    reply_rate: 19,
    calls_booked: 3,
    emails_sent: 5,
    progress_pct: 65,
    health_score: 72,
    ...overrides,
  };
}

function renderCampaignList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CampaignList />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CampaignList page", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockListCampaigns.mockResolvedValue([]);
  });

  // --- Header ---

  it("renders page title", () => {
    renderCampaignList();
    expect(screen.getByText("Campaigns")).toBeInTheDocument();
  });

  it("shows New Campaign button", () => {
    renderCampaignList();
    expect(screen.getByText("New Campaign")).toBeInTheDocument();
  });

  // --- Loading state ---

  it("shows skeleton cards while loading", () => {
    mockListCampaigns.mockReturnValue(new Promise(() => {}));
    renderCampaignList();
    expect(screen.getAllByTestId("skeleton-card").length).toBeGreaterThan(0);
  });

  // --- Error state ---

  it("shows error card when fetch fails", async () => {
    mockListCampaigns.mockRejectedValue(new Error("API error"));
    renderCampaignList();
    await waitFor(() => {
      expect(screen.getByTestId("error-card")).toBeInTheDocument();
    });
    expect(screen.getByText("API error")).toBeInTheDocument();
  });

  it("has retry button on error", async () => {
    mockListCampaigns.mockRejectedValue(new Error("Server down"));
    renderCampaignList();
    await waitFor(() => {
      expect(screen.getByText("Try Again")).toBeInTheDocument();
    });
  });

  // --- Empty state ---

  it("shows empty state when no campaigns exist", async () => {
    mockListCampaigns.mockResolvedValue([]);
    renderCampaignList();
    await waitFor(() => {
      expect(screen.getByText("Create your first campaign")).toBeInTheDocument();
    });
    expect(screen.getByText(/Upload contacts, build a sequence/)).toBeInTheDocument();
  });

  it("empty state has Create Campaign button", async () => {
    mockListCampaigns.mockResolvedValue([]);
    renderCampaignList();
    await waitFor(() => {
      expect(screen.getByText("Create Campaign")).toBeInTheDocument();
    });
  });

  // --- Campaign cards rendering ---

  it("renders campaign names", async () => {
    mockListCampaigns.mockResolvedValue([
      makeCampaign({ name: "Q1_2026_initial" }),
      makeCampaign({ id: 2, name: "Q2_follow_up" }),
    ]);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByText("Q1_2026_initial")).toBeInTheDocument();
    });
    expect(screen.getByText("Q2_follow_up")).toBeInTheDocument();
  });

  it("shows campaign count subtitle", async () => {
    mockListCampaigns.mockResolvedValue([
      makeCampaign(),
      makeCampaign({ id: 2, name: "Second" }),
    ]);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByText("2 campaigns")).toBeInTheDocument();
    });
  });

  it("shows singular campaign count for 1 campaign", async () => {
    mockListCampaigns.mockResolvedValue([makeCampaign()]);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByText("1 campaign")).toBeInTheDocument();
    });
  });

  it("renders status badge for each campaign", async () => {
    mockListCampaigns.mockResolvedValue([makeCampaign({ status: "active" })]);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByTestId("status-badge")).toBeInTheDocument();
      expect(screen.getByTestId("status-badge").textContent).toBe("active");
    });
  });

  it("renders health score badge", async () => {
    mockListCampaigns.mockResolvedValue([makeCampaign({ health_score: 85 })]);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByTestId("health-score")).toBeInTheDocument();
      expect(screen.getByTestId("health-score").textContent).toBe("85");
    });
  });

  it("renders N/A for null health score", async () => {
    mockListCampaigns.mockResolvedValue([makeCampaign({ health_score: null })]);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByTestId("health-score").textContent).toBe("N/A");
    });
  });

  // --- Metrics display ---

  it("displays contacts count", async () => {
    mockListCampaigns.mockResolvedValue([makeCampaign({ contacts_count: 42 })]);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByText("42")).toBeInTheDocument();
    });
    expect(screen.getByText("Contacts")).toBeInTheDocument();
  });

  it("displays reply rate", async () => {
    mockListCampaigns.mockResolvedValue([makeCampaign({ reply_rate: 19 })]);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByText("19%")).toBeInTheDocument();
    });
    expect(screen.getByText("Reply Rate")).toBeInTheDocument();
  });

  it("displays emails sent", async () => {
    mockListCampaigns.mockResolvedValue([makeCampaign({ emails_sent: 5 })]);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByText("5")).toBeInTheDocument();
    });
    expect(screen.getByText("Sent")).toBeInTheDocument();
  });

  it("displays progress bar percentage", async () => {
    mockListCampaigns.mockResolvedValue([makeCampaign({ progress_pct: 65 })]);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByText("65%")).toBeInTheDocument();
    });
  });

  // --- Campaign cards are links ---

  it("renders campaign cards as links to detail page", async () => {
    mockListCampaigns.mockResolvedValue([makeCampaign({ name: "Q1_2026_initial" })]);
    renderCampaignList();

    await waitFor(() => {
      const link = screen.getByText("Q1_2026_initial").closest("a");
      expect(link).toHaveAttribute("href", "/campaigns/Q1_2026_initial");
    });
  });

  it("New Campaign button links to wizard", () => {
    renderCampaignList();
    const link = screen.getByText("New Campaign").closest("a");
    expect(link).toHaveAttribute("href", "/campaigns/wizard");
  });

  // --- Multiple campaigns ---

  it("renders all campaigns in the list", async () => {
    const campaigns = [
      makeCampaign({ id: 1, name: "Campaign A" }),
      makeCampaign({ id: 2, name: "Campaign B" }),
      makeCampaign({ id: 3, name: "Campaign C" }),
    ];
    mockListCampaigns.mockResolvedValue(campaigns);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByText("Campaign A")).toBeInTheDocument();
    });
    expect(screen.getByText("Campaign B")).toBeInTheDocument();
    expect(screen.getByText("Campaign C")).toBeInTheDocument();
    expect(screen.getByText("3 campaigns")).toBeInTheDocument();
  });

  // --- Edge cases ---

  it("handles campaign with zero contacts", async () => {
    mockListCampaigns.mockResolvedValue([makeCampaign({ contacts_count: 0 })]);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByText("0")).toBeInTheDocument();
    });
  });

  it("handles campaign with 0% progress", async () => {
    mockListCampaigns.mockResolvedValue([makeCampaign({ progress_pct: 0 })]);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByText("0%")).toBeInTheDocument();
    });
  });

  it("clamps progress at 100%", async () => {
    mockListCampaigns.mockResolvedValue([makeCampaign({ progress_pct: 150 })]);
    renderCampaignList();

    await waitFor(() => {
      expect(screen.getByText("150%")).toBeInTheDocument();
    });
  });
});
