import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import QueueEmailCard from "../components/QueueEmailCard";
import type { QueueItem, MessageDraft } from "../types";

vi.mock("../api/client", () => ({
  api: {
    patchContact: vi.fn().mockResolvedValue({ success: true }),
    generateDraft: vi.fn().mockResolvedValue({}),
  },
}));

function makeQueueItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    contact_id: 1,
    contact_name: "Sarah Chen",
    company_name: "TestCo",
    channel: "email",
    step_order: 1,
    total_steps: 3,
    email: "sarah@testco.com",
    rendered_email: {
      subject: "Template Subject",
      body_text: "Template body text for TestCo.",
      body_html: "",
      contact_email: "sarah@testco.com",
    },
    campaign_id: 10,
    ...overrides,
  } as QueueItem;
}

const mockDraft: MessageDraft = {
  draft_subject: "AI Subject",
  draft_text: "AI-personalized body referencing portfolio rotation.",
  channel: "email",
  model: "claude-haiku-4-5-20251001",
  generated_at: "2026-03-25T12:00:00Z",
  research_id: 5,
};

function renderCard(item: QueueItem) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <QueueEmailCard item={item} campaign="test_campaign" />
    </QueryClientProvider>,
  );
}

describe("QueueEmailCard — AI draft rendering", () => {
  it("shows AI-drafted label when message_draft is present", () => {
    const item = makeQueueItem({ message_draft: mockDraft, draft_mode: "ai" });
    renderCard(item);
    expect(screen.getByText("AI-drafted from research")).toBeTruthy();
  });

  it("shows Generate AI Draft button when draft_mode=ai and no draft yet", () => {
    const item = makeQueueItem({
      draft_mode: "ai",
      has_research: true,
      message_draft: null,
    });
    renderCard(item);
    expect(screen.getByText("Generate AI Draft")).toBeTruthy();
  });

  it("shows CTA message when draft_mode=ai and no draft generated", () => {
    const item = makeQueueItem({
      draft_mode: "ai",
      has_research: true,
      message_draft: null,
    });
    renderCard(item);
    expect(screen.getByText("Generate AI draft to personalize this message")).toBeTruthy();
  });
});
