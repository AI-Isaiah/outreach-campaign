import type { Campaign, CampaignResponse, CampaignMetricsResponse, TemplatePerformanceItem, WeeklySummary } from "../types";
import { request } from "./request";

export interface CampaignWithMetrics extends Campaign {
  contacts_count: number;
  replied_count: number;
  reply_rate: number;
  calls_booked: number;
  progress_pct: number;
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
  listCampaigns: () => request<CampaignWithMetrics[]>("/campaigns"),
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
};
