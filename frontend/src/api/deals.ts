import type { Deal, DealPipeline, DealListResponse, DealResponse } from "../types";
import { request } from "./request";

export const dealsApi = {
  getDealPipeline: (campaignId?: number) => {
    const p = new URLSearchParams();
    if (campaignId != null) p.set("campaign_id", String(campaignId));
    return request<DealPipeline>(`/deals/pipeline?${p}`);
  },
  listDeals: (params?: { stage?: string; company_id?: number; page?: number }) => {
    const p = new URLSearchParams();
    if (params?.stage) p.set("stage", params.stage);
    if (params?.company_id != null) p.set("company_id", String(params.company_id));
    if (params?.page) p.set("page", String(params.page));
    return request<DealListResponse>(`/deals?${p}`);
  },
  createDeal: (data: {
    company_id: number; contact_id?: number; campaign_id?: number;
    title: string; stage?: string; amount_millions?: number; notes?: string;
  }) =>
    request<{ id: number; success: boolean }>("/deals", {
      method: "POST", body: JSON.stringify(data),
    }),
  getDeal: (id: number) => request<DealResponse>(`/deals/${id}`),
  updateDeal: (id: number, data: Partial<Deal>) =>
    request<{ success: boolean }>(`/deals/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  updateDealStage: (id: number, stage: string) =>
    request<{ success: boolean }>(`/deals/${id}/stage`, { method: "PATCH", body: JSON.stringify({ stage }) }),
  deleteDeal: (id: number) => request<{ success: boolean }>(`/deals/${id}`, { method: "DELETE" }),
};
