import type { Campaign, CampaignResponse, CampaignMetricsResponse, WeeklySummary } from "../types";
import { request } from "./request";

export const campaignsApi = {
  listCampaigns: () => request<Campaign[]>("/campaigns"),
  createCampaign: (data: { name: string; description?: string; status?: string }) =>
    request<{ id: number; success: boolean }>("/campaigns", {
      method: "POST", body: JSON.stringify(data),
    }),
  getCampaign: (name: string) => request<CampaignResponse>(`/campaigns/${name}`),
  getCampaignMetrics: (name: string) => request<CampaignMetricsResponse>(`/campaigns/${name}/metrics`),
  getCampaignWeekly: (name: string, weeksBack = 1) =>
    request<{ weekly: WeeklySummary }>(`/campaigns/${name}/weekly?weeks_back=${weeksBack}`),
  getCampaignReport: (name: string) => request<{ report: string }>(`/campaigns/${name}/report`),
};
