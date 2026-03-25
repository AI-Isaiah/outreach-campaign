import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import QueueLinkedInCard from "./QueueLinkedInCard";
import type { QueueItem } from "../types";

vi.mock("../api/client", () => ({
  api: {
    markLinkedInDone: vi.fn().mockResolvedValue({ success: true }),
    deferContact: vi.fn().mockResolvedValue({ success: true }),
    updateContactName: vi.fn().mockResolvedValue({ success: true }),
    updateLinkedInUrl: vi.fn().mockResolvedValue({ success: true }),
  },
}));

function makeItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    contact_id: 1,
    contact_name: "Jane Smith",
    company_name: "Pantera Capital",
    company_id: 10,
    aum_millions: 5000,
    firm_type: "Hedge Fund",
    aum_tier: "large",
    channel: "linkedin_connect",
    step_order: 1,
    total_steps: 3,
    template_id: 5,
    is_gdpr: false,
    email: "jane@pantera.com",
    linkedin_url: "https://linkedin.com/in/janesmith",
    rendered_message: "Hi Jane, I'd love to connect about our fund strategy.",
    sales_nav_url: "https://linkedin.com/sales/people/janesmith",
    campaign_name: "Q1_2026",
    campaign_id: 1,
    ...overrides,
  };
}

function renderCard(item: QueueItem, campaign = "Q1_2026") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <QueueLinkedInCard item={item} campaign={campaign} />
    </QueryClientProvider>,
  );
}

describe("QueueLinkedInCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders message text in textarea", () => {
    const item = makeItem();
    renderCard(item);

    const textarea = screen.getByDisplayValue(item.rendered_message!);
    expect(textarea).toBeInTheDocument();
    expect(textarea).toHaveAttribute("readonly");
  });

  it("copies message to clipboard on copy button click", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    const item = makeItem();
    renderCard(item);

    const copyBtn = screen.getByRole("button", { name: "Copy message to clipboard" });
    expect(copyBtn).toBeInTheDocument();

    await user.click(copyBtn);

    expect(writeText).toHaveBeenCalledWith(item.rendered_message);
    expect(screen.getByText("Copied")).toBeInTheDocument();
  });

  it("shows contact info without message section when no template", () => {
    const item = makeItem({ rendered_message: null });
    renderCard(item);

    expect(screen.getByText("Jane Smith")).toBeInTheDocument();
    expect(screen.getByText(/Pantera Capital/)).toBeInTheDocument();
    expect(screen.queryByText("Message")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy message to clipboard" })).not.toBeInTheDocument();
  });

  it("toggles message visibility when clicking Message label", async () => {
    const user = userEvent.setup();
    const item = makeItem();
    renderCard(item);

    // Message visible by default
    expect(screen.getByDisplayValue(item.rendered_message!)).toBeInTheDocument();

    // Click Message toggle to collapse
    const toggleBtn = screen.getByRole("button", { name: /^message$/i });
    await user.click(toggleBtn);

    // Textarea should be hidden
    expect(screen.queryByDisplayValue(item.rendered_message!)).not.toBeInTheDocument();

    // Copy button should still be visible
    expect(screen.getByRole("button", { name: "Copy message to clipboard" })).toBeInTheDocument();

    // Click again to expand
    await user.click(toggleBtn);
    expect(screen.getByDisplayValue(item.rendered_message!)).toBeInTheDocument();
  });
});
