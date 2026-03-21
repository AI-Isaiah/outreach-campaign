import type { NewsletterDetail, NewsletterListResponse, RecipientPreview } from "../types";
import { BASE, authHeaders, request } from "./request";

export const newslettersApi = {
  listNewsletters: (page = 1) =>
    request<NewsletterListResponse>(`/newsletters?page=${page}`),

  createNewsletter: (data: { subject: string; body_html: string; body_text?: string }) =>
    request<{ id: number; success: boolean }>("/newsletters", {
      method: "POST", body: JSON.stringify(data),
    }),

  getNewsletter: (id: number) => request<NewsletterDetail>(`/newsletters/${id}`),

  updateNewsletter: (id: number, data: { subject?: string; body_html?: string; body_text?: string }) =>
    request<{ success: boolean }>(`/newsletters/${id}`, {
      method: "PUT", body: JSON.stringify(data),
    }),

  deleteNewsletter: (id: number) =>
    request<{ success: boolean }>(`/newsletters/${id}`, { method: "DELETE" }),

  uploadNewsletterAttachment: async (newsletterId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${BASE}/newsletters/${newsletterId}/attachments`, {
      method: "POST", body: formData, headers: authHeaders(),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }
    return res.json() as Promise<{ id: number; filename: string; success: boolean }>;
  },

  deleteNewsletterAttachment: (newsletterId: number, attachmentId: number) =>
    request<{ success: boolean }>(`/newsletters/${newsletterId}/attachments/${attachmentId}`, { method: "DELETE" }),

  previewRecipients: (newsletterId: number, params?: {
    lifecycle_stages?: string[]; product_ids?: number[]; newsletter_only?: boolean;
  }) => {
    const p = new URLSearchParams();
    if (params?.lifecycle_stages?.length) p.set("lifecycle_stages", params.lifecycle_stages.join(","));
    if (params?.product_ids?.length) p.set("product_ids", params.product_ids.join(","));
    if (params?.newsletter_only != null) p.set("newsletter_only", String(params.newsletter_only));
    return request<RecipientPreview>(`/newsletters/${newsletterId}/recipients?${p}`);
  },

  sendNewsletter: (id: number, data: {
    lifecycle_stages?: string[]; product_ids?: number[]; newsletter_only?: boolean;
  }) =>
    request<{ sent: number; failed: number; total: number }>(`/newsletters/${id}/send`, {
      method: "POST", body: JSON.stringify(data),
    }),
};
