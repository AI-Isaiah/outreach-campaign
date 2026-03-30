import type {
  CsvPreview, CreateResearchJobResponse, ResearchJobsResponse,
  ResearchJobDetail, ResearchResultsResponse, ResearchResult, BatchImportResponse,
} from "../types";
import { BASE, request, requestUpload } from "./request";

export const researchApi = {
  previewResearchCsv: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return requestUpload<CsvPreview>("/research/preview-csv", formData);
  },

  createResearchJob: async (file: File, name: string, method = "hybrid", skipDuplicates = true) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("name", name);
    formData.append("method", method);
    formData.append("skip_duplicates", String(skipDuplicates));
    return requestUpload<CreateResearchJobResponse>("/research/jobs", formData);
  },

  listResearchJobs: (status?: string, page = 1) => {
    const p = new URLSearchParams({ page: String(page) });
    if (status) p.set("status", status);
    return request<ResearchJobsResponse>(`/research/jobs?${p}`);
  },

  getResearchJob: (id: number) => request<ResearchJobDetail>(`/research/jobs/${id}`),

  getResearchResults: (jobId: number, filters?: {
    category?: string; min_score?: number; has_warm_intros?: boolean;
    sort_by?: string; sort_dir?: string; page?: number;
  }) => {
    const p = new URLSearchParams();
    if (filters?.category) p.set("category", filters.category);
    if (filters?.min_score != null) p.set("min_score", String(filters.min_score));
    if (filters?.has_warm_intros != null) p.set("has_warm_intros", String(filters.has_warm_intros));
    if (filters?.sort_by) p.set("sort_by", filters.sort_by);
    if (filters?.sort_dir) p.set("sort_dir", filters.sort_dir);
    if (filters?.page) p.set("page", String(filters.page));
    return request<ResearchResultsResponse>(`/research/jobs/${jobId}/results?${p}`);
  },

  getResearchResult: (id: number) => request<ResearchResult>(`/research/results/${id}`),

  importDiscoveredContacts: (resultId: number, indices: number[]) =>
    request<{ success: boolean; imported: number; company_id: number }>(
      `/research/results/${resultId}/import-contacts`,
      { method: "POST", body: JSON.stringify(indices) },
    ),

  batchImport: (resultIds: number[], createDeals = false, campaignName?: string) =>
    request<BatchImportResponse>(`/research/batch-import`, {
      method: "POST",
      body: JSON.stringify({ result_ids: resultIds, create_deals: createDeals, campaign_name: campaignName }),
    }),

  cancelResearchJob: (id: number) =>
    request<{ success: boolean }>(`/research/jobs/${id}/cancel`, { method: "POST" }),

  retryResearchJob: (id: number) =>
    request<{ success: boolean; retrying: number }>(`/research/jobs/${id}/retry`, { method: "POST" }),

  exportResearchResults: (jobId: number, minScore?: number, categories?: string[]) => {
    const p = new URLSearchParams();
    if (minScore != null) p.set("min_score", String(minScore));
    if (categories?.length) p.set("categories", categories.join(","));
    window.open(`${BASE}/research/jobs/${jobId}/export?${p}`, "_blank");
  },

  deleteResearchJob: (id: number) =>
    request<{ success: boolean }>(`/research/jobs/${id}`, { method: "DELETE" }),
};
