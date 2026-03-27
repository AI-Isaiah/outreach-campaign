import type { QueueResponse, DeferStatsResponse } from "../types";
import { request } from "./request";

export const queueApi = {
  getAllQueues: (options?: { date?: string; limit?: number }) => {
    const params = new URLSearchParams({ limit: String(options?.limit ?? 50) });
    if (options?.date) params.set("date", options.date);
    return request<QueueResponse>(`/queue/all?${params}`);
  },

  getQueue: (campaign: string, options?: {
    date?: string; limit?: number; firm_type?: string; aum_min?: number; aum_max?: number;
  }) => {
    const params = new URLSearchParams({ limit: String(options?.limit ?? 25) });
    if (options?.date) params.set("date", options.date);
    if (options?.firm_type) params.set("firm_type", options.firm_type);
    if (options?.aum_min != null) params.set("aum_min", String(options.aum_min));
    if (options?.aum_max != null) params.set("aum_max", String(options.aum_max));
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

  batchApprove: (items: { contact_id: number; campaign_id: number }[]) =>
    request<{ approved: number }>("/queue/batch-approve", {
      method: "POST",
      body: JSON.stringify({ items }),
    }),

  batchSend: (options?: { contact_ids?: number[]; scheduled_for?: string }) =>
    request<{ sent: number; failed: number; errors: { contact_id: number; campaign_id: number; error: string }[] }>(
      "/queue/batch-send",
      { method: "POST", body: options ? JSON.stringify(options) : undefined },
    ),

  scheduleSend: (items: { contact_id: number; campaign_id: number }[], schedule: string) =>
    request<{ scheduled: number }>("/queue/schedule", {
      method: "POST",
      body: JSON.stringify({ items, schedule }),
    }),

  batchCancel: (contactIds: number[]) =>
    request<{ cancelled: number }>("/queue/batch-cancel", {
      method: "POST",
      body: JSON.stringify({ contact_ids: contactIds }),
    }),
};
