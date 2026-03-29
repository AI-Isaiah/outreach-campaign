import type { Campaign, CampaignResponse, CampaignMetricsResponse, TemplatePerformanceItem, WeeklySummary } from "../types";
import { request } from "./request";

export interface CampaignWithMetrics extends Campaign {
  contacts_count: number;
  replied_count: number;
  reply_rate: number;
  calls_booked: number;
  progress_pct: number;
  health_score: number | null;
}

export interface SequenceStepInput {
  step_order: number;
  channel: string;
  delay_days: number;
  template_id?: number | null;
  draft_mode?: 'template' | 'ai';
}

export interface LaunchCampaignRequest {
  name: string;
  description?: string;
  steps: SequenceStepInput[];
  contact_ids: number[];
  status?: "active" | "draft";
}

export interface LaunchCampaignResponse {
  campaign_id: number;
  name: string;
  status: string;
  contacts_enrolled: number;
  steps_created: number;
}

export interface CampaignContact {
  id: number;
  first_name: string;
  last_name: string;
  full_name: string;
  email: string;
  linkedin_url: string;
  title: string;
  company_name: string;
  company_id: number;
  current_step: number;
  current_channel: string | null;
  status: string;
  next_action_date: string;
  total_steps: number;
}

export interface GeneratedStep {
  _id: string;
  step_order: number;
  channel: string;
  delay_days: number;
  template_id: number | null;
  draft_mode?: 'template' | 'ai';
}

export const campaignsApi = {
  listCampaigns: (status?: string) =>
    request<CampaignWithMetrics[]>(`/campaigns${status ? `?status=${status}` : ""}`),
  createCampaign: (data: { name: string; description?: string; status?: string }) =>
    request<{ id: number; success: boolean }>("/campaigns", {
      method: "POST", body: JSON.stringify(data),
    }),
  getCampaign: (name: string) => request<CampaignResponse>(`/campaigns/${name}`),
  getCampaignMetrics: (name: string) => request<CampaignMetricsResponse>(`/campaigns/${name}/metrics`),
  getCampaignWeekly: (name: string, weeksBack = 1) =>
    request<{ weekly: WeeklySummary }>(`/campaigns/${name}/weekly?weeks_back=${weeksBack}`),
  getCampaignReport: (name: string) => request<{ report: string }>(`/campaigns/${name}/report`),
  getTemplatePerformance: (name: string) => request<TemplatePerformanceItem[]>(`/campaigns/${name}/template-performance`),

  launchCampaign: (data: LaunchCampaignRequest) =>
    request<LaunchCampaignResponse>("/campaigns/launch", {
      method: "POST", body: JSON.stringify(data),
    }),

  updateCampaignStatus: (name: string, status: "active" | "paused" | "archived") =>
    request<{ name: string; status: string }>(`/campaigns/${name}/status`, {
      method: "PATCH", body: JSON.stringify({ status }),
    }),

  deleteCampaign: (name: string) =>
    request<{ name: string; deleted: boolean }>(`/campaigns/${name}`, { method: "DELETE" }),

  enrollContacts: (campaignId: number, contactIds: number[]) =>
    request<{ enrolled: number; campaign_id: number }>(`/campaigns/${campaignId}/enroll`, {
      method: "POST",
      body: JSON.stringify({ contact_ids: contactIds }),
    }),

  getCampaignContacts: (campaignId: number, options?: { status?: string; sort?: string }) => {
    const params = new URLSearchParams();
    if (options?.status) params.set("status", options.status);
    if (options?.sort) params.set("sort", options.sort);
    const qs = params.toString();
    return request<CampaignContact[]>(`/campaigns/${campaignId}/contacts${qs ? `?${qs}` : ""}`);
  },

  generateSequence: (campaignId: number, data: { touchpoints: number; channels: string[] }) =>
    request<{ steps: GeneratedStep[] }>(`/campaigns/${campaignId}/generate-sequence`, {
      method: "POST", body: JSON.stringify(data),
    }),

  reorderSequence: (campaignId: number, steps: { step_id: number; step_order: number; delay_days?: number; channel?: string }[]) =>
    request<{ affected_count: number }>(`/campaigns/${campaignId}/sequence/reorder`, {
      method: "PUT", body: JSON.stringify({ steps }),
    }),

  updateSequenceStep: (campaignId: number, stepId: number, updates: { channel?: string; delay_days?: number; template_id?: number }) =>
    request<{ success: boolean }>(`/campaigns/${campaignId}/sequence/${stepId}`, {
      method: "PATCH", body: JSON.stringify(updates),
    }),

  addSequenceStep: (campaignId: number, step: { channel: string; delay_days?: number; template_id?: number; step_order?: number }) =>
    request<{ id: number; success: boolean }>(`/campaigns/${campaignId}/sequence`, {
      method: "POST", body: JSON.stringify(step),
    }),

  deleteSequenceStep: (campaignId: number, stepId: number) =>
    request<{ success: boolean }>(`/campaigns/${campaignId}/sequence/${stepId}`, {
      method: "DELETE",
    }),

  getCampaignMessages: (campaignId: number, params: { limit?: number; offset?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.limit) query.set("limit", String(params.limit));
    if (params.offset) query.set("offset", String(params.offset));
    const qs = query.toString();
    return request<{ messages: Record<string, unknown>[]; total: number }>(`/campaigns/${campaignId}/messages${qs ? `?${qs}` : ""}`);
  },
};
