import type { QueueResponse, DeferStatsResponse } from "../types";
import { authHeaders, BASE, request } from "./request";

export const queueApi = {
  getAllQueues: (options?: { date?: string; limit?: number }) => {
    const params = new URLSearchParams({ limit: String(options?.limit ?? 50) });
    if (options?.date) params.set("date", options.date);
    return request<QueueResponse>(`/queue/all?${params}`);
  },

  getQueue: (campaign: string, options?: {
    date?: string; limit?: number; firm_type?: string; aum_min?: number; aum_max?: number; scope?: string;
  }) => {
    const params = new URLSearchParams({ limit: String(options?.limit ?? 25) });
    if (options?.date) params.set("date", options.date);
    if (options?.firm_type) params.set("firm_type", options.firm_type);
    if (options?.aum_min != null) params.set("aum_min", String(options.aum_min));
    if (options?.aum_max != null) params.set("aum_max", String(options.aum_max));
    if (options?.scope) params.set("scope", options.scope);
    return request<QueueResponse>(`/queue/${campaign}?${params}`);
  },

  markLinkedInDone: (contactId: number, actionType: string, campaign: string) =>
    request<{ success: boolean }>(`/queue/${contactId}/linkedin-done?campaign=${campaign}`, {
      method: "POST", body: JSON.stringify({ action_type: actionType }),
    }),

  overrideTemplate: (campaign: string, contactId: number, templateId: number) =>
    request<{ success: boolean }>(`/queue/${campaign}/override`, {
      method: "POST", body: JSON.stringify({ contact_id: contactId, template_id: templateId }),
    }),

  deferContact: (contactId: number, campaign: string, reason?: string) =>
    request<{ success: boolean }>(`/queue/${contactId}/defer`, {
      method: "POST", body: JSON.stringify({ campaign, reason }),
    }),

  getDeferStats: (campaign?: string) => {
    const params = new URLSearchParams();
    if (campaign) params.set("campaign", campaign);
    return request<DeferStatsResponse>(`/queue/defer/stats?${params}`);
  },

  generateDraft: (contactId: number, campaignId: number, stepOrder: number) =>
    request<{ draft_subject: string | null; draft_text: string; model: string; channel: string; generated_at: string; has_research: boolean }>(
      `/queue/${contactId}/generate-draft`,
      { method: "POST", body: JSON.stringify({ campaign_id: campaignId, step_order: stepOrder }) }
    ),

  batchApprove: async (
    items: { contact_id: number; campaign_id: number }[],
    force = false,
  ): Promise<{ approved: number; validation_errors: null } | { approved: 0; validation_errors: { error: string; company_duplicates?: { company_id: number; company_name: string; count: number }[]; email_duplicates?: { email: string; count: number }[] } }> => {
    const url = `${BASE}/queue/batch-approve${force ? "?force=true" : ""}`;
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ items }),
    });
    if (res.status === 401) {
      localStorage.removeItem("auth_token");
      window.dispatchEvent(new Event("auth:expired"));
      throw new Error("Session expired");
    }
    if (res.status === 400) {
      const data = await res.json();
      return { approved: 0, validation_errors: data };
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const result = await res.json();
    return { ...result, validation_errors: null };
  },

  batchSend: (opts?: { signal?: AbortSignal }) =>
    request<{ sent: number; failed: number; remaining: number; errors: { contact_id: number; campaign_id: number; error: string }[] }>(
      "/queue/batch-send",
      { method: "POST", ...(opts?.signal ? { signal: opts.signal } : {}) },
    ),

  scheduleSend: (items: { contact_id: number; campaign_id: number }[], schedule: string) =>
    request<{ scheduled: number }>("/queue/schedule", {
      method: "POST",
      body: JSON.stringify({ items, schedule }),
    }),

  undoSend: () =>
    request<{ undone: number }>("/queue/undo-send", { method: "POST" }),
};
