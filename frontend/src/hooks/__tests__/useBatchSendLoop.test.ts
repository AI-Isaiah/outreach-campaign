import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { useBatchSendLoop } from "../useBatchSendLoop";

// Mock the queue API
vi.mock("../../api/queue", () => ({
  queueApi: {
    batchApprove: vi.fn(),
    batchSend: vi.fn(),
    undoSend: vi.fn(),
  },
}));

import { queueApi } from "../../api/queue";

const mockApprove = vi.mocked(queueApi.batchApprove);
const mockSend = vi.mocked(queueApi.batchSend);
const mockUndo = vi.mocked(queueApi.undoSend);

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
}

const makeItem = (id: number, campId = 1) => ({
  contact_id: id,
  campaign_id: campId,
  contact_name: `Contact ${id}`,
  company_name: "TestCo",
  channel: "email" as const,
  step_order: 1,
  template_id: 1,
  is_gdpr: false,
  email: `c${id}@test.com`,
  linkedin_url: null,
  email_status: "valid",
}) as any;

describe("useBatchSendLoop", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("starts in idle state", () => {
    const { result } = renderHook(() => useBatchSendLoop(), { wrapper: createWrapper() });
    expect(result.current.sendPhase).toBe("idle");
    expect(result.current.sendProgress).toBeNull();
    expect(result.current.validationErrors).toBeNull();
    expect(result.current.undoCountdown).toBeNull();
  });

  it("transitions idle → approving → sending → done on success", async () => {
    mockApprove.mockResolvedValue({ approved: 2, validation_errors: null });
    mockSend.mockResolvedValueOnce({ sent: 2, failed: 0, remaining: 0, errors: [] });

    const items = [makeItem(1), makeItem(2)];
    const ids = new Set([1, 2]);
    const { result } = renderHook(() => useBatchSendLoop(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.handleConfirmSend(false, items, ids);
    });

    expect(mockApprove).toHaveBeenCalledWith(
      [{ contact_id: 1, campaign_id: 1 }, { contact_id: 2, campaign_id: 1 }],
      false,
    );
    expect(mockSend).toHaveBeenCalled();
    expect(result.current.sendPhase).toBe("done");
    expect(result.current.sendProgress).toEqual({ sent: 2, failed: 0, total: 2 });
    expect(result.current.undoCountdown).toBe(30);
  });

  it("returns to idle with validation errors on 400", async () => {
    mockApprove.mockResolvedValue({
      approved: 0,
      validation_errors: { error: "Validation failed", email_duplicates: [{ email: "alice@test.com", count: 2 }] },
    });

    const items = [makeItem(1)];
    const ids = new Set([1]);
    const { result } = renderHook(() => useBatchSendLoop(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.handleConfirmSend(false, items, ids);
    });

    expect(result.current.sendPhase).toBe("idle");
    expect(result.current.validationErrors).toEqual({ error: "Validation failed", email_duplicates: [{ email: "alice@test.com", count: 2 }] });
    expect(mockSend).not.toHaveBeenCalled();
  });

  it("transitions to error on approve network failure", async () => {
    mockApprove.mockRejectedValue(new Error("Network error"));

    const { result } = renderHook(() => useBatchSendLoop(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.handleConfirmSend(false, [makeItem(1)], new Set([1]));
    });

    expect(result.current.sendPhase).toBe("error");
  });

  it("breaks infinite loop when send returns 0 sent with remaining > 0", async () => {
    mockApprove.mockResolvedValue({ approved: 1, validation_errors: null });
    mockSend.mockResolvedValue({ sent: 0, failed: 0, remaining: 5, errors: [] });

    const { result } = renderHook(() => useBatchSendLoop(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.handleConfirmSend(false, [makeItem(1)], new Set([1]));
    });

    // Should have called send exactly once, then broken out of the loop
    expect(mockSend).toHaveBeenCalledTimes(1);
    expect(result.current.sendPhase).toBe("done");
  });

  it("resetState clears everything back to idle", async () => {
    mockApprove.mockResolvedValue({ approved: 1, validation_errors: null });
    mockSend.mockResolvedValue({ sent: 1, failed: 0, remaining: 0, errors: [] });

    const { result } = renderHook(() => useBatchSendLoop(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.handleConfirmSend(false, [makeItem(1)], new Set([1]));
    });
    expect(result.current.sendPhase).toBe("done");

    act(() => {
      result.current.resetState();
    });

    expect(result.current.sendPhase).toBe("idle");
    expect(result.current.sendProgress).toBeNull();
    expect(result.current.undoCountdown).toBeNull();
    expect(result.current.validationErrors).toBeNull();
  });

  it("handleUndo calls API and resets to idle", async () => {
    mockApprove.mockResolvedValue({ approved: 1, validation_errors: null });
    mockSend.mockResolvedValue({ sent: 1, failed: 0, remaining: 0, errors: [] });
    mockUndo.mockResolvedValue({ undone: 1 });

    const { result } = renderHook(() => useBatchSendLoop(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.handleConfirmSend(false, [makeItem(1)], new Set([1]));
    });
    expect(result.current.sendPhase).toBe("done");

    await act(async () => {
      await result.current.handleUndo();
    });

    expect(mockUndo).toHaveBeenCalled();
    expect(result.current.sendPhase).toBe("idle");
    expect(result.current.sendProgress).toBeNull();
    expect(result.current.undoCountdown).toBeNull();
  });

  it("only sends items matching selectedIds", async () => {
    mockApprove.mockResolvedValue({ approved: 1, validation_errors: null });
    mockSend.mockResolvedValue({ sent: 1, failed: 0, remaining: 0, errors: [] });

    const items = [makeItem(1), makeItem(2), makeItem(3)];
    const ids = new Set([1, 3]); // Skip contact 2

    const { result } = renderHook(() => useBatchSendLoop(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.handleConfirmSend(false, items, ids);
    });

    // batchApprove should only get contact 1 and 3
    expect(mockApprove).toHaveBeenCalledWith(
      [{ contact_id: 1, campaign_id: 1 }, { contact_id: 3, campaign_id: 1 }],
      false,
    );
  });

  it("multi-batch send accumulates progress", async () => {
    mockApprove.mockResolvedValue({ approved: 3, validation_errors: null });
    mockSend
      .mockResolvedValueOnce({ sent: 2, failed: 0, remaining: 1, errors: [] })
      .mockResolvedValueOnce({ sent: 1, failed: 0, remaining: 0, errors: [] });

    const items = [makeItem(1), makeItem(2), makeItem(3)];
    const ids = new Set([1, 2, 3]);

    const { result } = renderHook(() => useBatchSendLoop(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.handleConfirmSend(false, items, ids);
    });

    expect(mockSend).toHaveBeenCalledTimes(2);
    expect(result.current.sendProgress).toEqual({ sent: 3, failed: 0, total: 3 });
    expect(result.current.sendPhase).toBe("done");
  });
});
