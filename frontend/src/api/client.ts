/**
 * Unified API client — backward-compatible combined export.
 *
 * All methods are split into domain modules under `api/`.
 * This file re-composes them into the single `api` object that
 * existing pages import.
 */

import type {
  SearchResults, EngineSettings, Template, PendingReply, PendingRepliesResponse,
  TimelineResponse, CompanyDetailResponse, Tag, InboxResponse, StatsResponse,
  ContactListResponse, CompanyListResponse, AnalysisResponse,
  ImportResponse, Product, ContactProduct, LinkedInScanResponse, ReplyScanResponse,
} from "../types";

import { BASE, authHeaders, request } from "./request";
import { queueApi } from "./queue";
import { campaignsApi } from "./campaigns";
import { contactsApi } from "./contacts";
import { dealsApi } from "./deals";
import { newslettersApi } from "./newsletters";
import { researchApi } from "./research";

export const api = {
  // Domain modules (spread)
  ...queueApi,
  ...campaignsApi,
  ...contactsApi,
  ...dealsApi,
  ...newslettersApi,
  ...researchApi,

  // Stats
  getStats: () => request<StatsResponse>("/stats"),

  // Gmail
  getGmailStatus: () => request<EngineSettings>("/gmail/status"),
  authorizeGmail: () => request<{ authorization_url: string }>("/gmail/authorize", { method: "POST" }),
  createDraft: (contactId: number, campaign: string, templateId: number, subject?: string, bodyText?: string) =>
    request<{ draft_id: string; success: boolean }>("/gmail/drafts", {
      method: "POST",
      body: JSON.stringify({ contact_id: contactId, campaign, template_id: templateId, subject, body_text: bodyText }),
    }),
  createBatchDrafts: (campaign: string, date?: string) =>
    request<{ created: number; success: boolean }>("/gmail/drafts/batch", {
      method: "POST", body: JSON.stringify({ campaign, date }),
    }),
  checkDraftStatus: (contactId: number, campaign: string) =>
    request<{ draft_id: string; status: string }>(`/gmail/drafts/${contactId}?campaign=${campaign}`),

  // Templates
  listTemplates: (channel?: string, active = true) => {
    const params = new URLSearchParams({ active: String(active) });
    if (channel) params.set("channel", channel);
    return request<Template[]>(`/templates?${params}`);
  },
  getTemplate: (id: number) => request<Template>(`/templates/${id}`),
  createTemplate: (data: {
    name: string; channel: string; body_template: string;
    subject?: string; variant_group?: string; variant_label?: string;
  }) =>
    request<{ id: number; success: boolean }>("/templates", {
      method: "POST", body: JSON.stringify(data),
    }),
  updateTemplate: (id: number, data: Partial<Template>) =>
    request<{ success: boolean }>(`/templates/${id}`, {
      method: "PUT", body: JSON.stringify(data),
    }),
  deactivateTemplate: (id: number) =>
    request<{ success: boolean }>(`/templates/${id}/deactivate`, { method: "PATCH" }),
  generateSequenceMessages: (data: {
    steps: Array<{ step_order: number; channel: string; delay_days: number }>;
    product_description: string;
    target_audience?: string;
  }) =>
    request<{ messages: Array<{ step_order: number; channel: string; subject: string | null; body: string }> }>(
      "/templates/generate-sequence",
      { method: "POST", body: JSON.stringify(data) },
    ),
  improveMessage: (data: {
    channel: string;
    body: string;
    subject?: string;
    instruction: string;
  }) =>
    request<{ subject: string | null; body: string }>("/templates/improve-message", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Pending Replies
  listPendingReplies: () => request<PendingRepliesResponse>("/replies/pending"),
  confirmReply: (id: number, outcome: string, note?: string) =>
    request<{ success: boolean }>(`/replies/${id}/confirm`, {
      method: "POST", body: JSON.stringify({ outcome, note }),
    }),
  scanReplies: () => request<ReplyScanResponse>("/replies/scan", { method: "POST" }),
  scanLinkedInAcceptances: () => request<LinkedInScanResponse>("/replies/scan-linkedin", { method: "POST" }),

  // Products
  listProducts: () => request<Product[]>("/products"),
  createProduct: (name: string, description?: string) =>
    request<{ id: number; success: boolean }>("/products", {
      method: "POST", body: JSON.stringify({ name, description }),
    }),
  listContactProducts: (contactId: number) =>
    request<ContactProduct[]>(`/contacts/${contactId}/products`),
  linkContactProduct: (contactId: number, productId: number, stage = "discussed", notes?: string) =>
    request<{ id: number; success: boolean }>(`/contacts/${contactId}/products`, {
      method: "POST", body: JSON.stringify({ product_id: productId, stage, notes }),
    }),
  updateContactProductStage: (contactId: number, productId: number, stage: string) =>
    request<{ success: boolean }>(`/contacts/${contactId}/products/${productId}/stage`, {
      method: "PATCH", body: JSON.stringify({ stage }),
    }),
  removeContactProduct: (contactId: number, productId: number) =>
    request<{ success: boolean }>(`/contacts/${contactId}/products/${productId}`, { method: "DELETE" }),

  // CRM
  listCrmContacts: (params?: {
    search?: string; status?: string; company_type?: string;
    min_aum?: number; max_aum?: number; lifecycle_stage?: string;
    newsletter_subscriber?: boolean; product_id?: number; page?: number;
    sort_by?: string; sort_dir?: "asc" | "desc";
  }) => {
    const p = new URLSearchParams();
    if (params?.search) p.set("search", params.search);
    if (params?.status) p.set("status", params.status);
    if (params?.company_type) p.set("company_type", params.company_type);
    if (params?.min_aum != null) p.set("min_aum", String(params.min_aum));
    if (params?.max_aum != null) p.set("max_aum", String(params.max_aum));
    if (params?.lifecycle_stage) p.set("lifecycle_stage", params.lifecycle_stage);
    if (params?.newsletter_subscriber != null) p.set("newsletter_subscriber", String(params.newsletter_subscriber));
    if (params?.product_id != null) p.set("product_id", String(params.product_id));
    if (params?.page) p.set("page", String(params.page));
    if (params?.sort_by) p.set("sort_by", params.sort_by);
    if (params?.sort_dir) p.set("sort_dir", params.sort_dir);
    return request<ContactListResponse>(`/crm/contacts?${p}`);
  },

  getContactTimeline: (id: number, page = 1) =>
    request<TimelineResponse>(`/crm/contacts/${id}/timeline?page=${page}`),

  listCompanies: (params?: { search?: string; firm_type?: string; page?: number; per_page?: number }) => {
    const p = new URLSearchParams();
    if (params?.search) p.set("search", params.search);
    if (params?.firm_type) p.set("firm_type", params.firm_type);
    if (params?.page) p.set("page", String(params.page));
    if (params?.per_page) p.set("per_page", String(params.per_page));
    return request<CompanyListResponse>(`/crm/companies?${p}`);
  },

  getCompany: (id: number) => request<CompanyDetailResponse>(`/crm/companies/${id}`),
  globalSearch: (q: string) => request<SearchResults>(`/crm/search?q=${encodeURIComponent(q)}`),

  // Settings
  getSettings: () => request<EngineSettings>("/settings"),
  updateSettings: (settings: Record<string, string>) =>
    request<{ success: boolean }>("/settings", {
      method: "PUT", body: JSON.stringify({ settings }),
    }),

  // Import
  runDedupe: () => request<ImportResponse>("/import/dedupe", { method: "POST" }),
  importCsv: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${BASE}/import/csv`, { method: "POST", body: formData, headers: authHeaders() });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }
    return res.json() as Promise<{ imported: number; skipped: number; errors: string[] }>;
  },

  // Insights
  runAnalysis: (campaignId: number) =>
    request<AnalysisResponse>("/insights/analyze", {
      method: "POST", body: JSON.stringify({ campaign_id: campaignId }),
    }),
  getInsightHistory: () => request<AnalysisResponse[]>("/insights/history"),

  // WhatsApp
  whatsappSetup: () => request<{ success: boolean }>("/whatsapp/setup", { method: "POST" }),
  whatsappScan: () => request<{ scanned: number; new_messages: number; success: boolean }>("/whatsapp/scan", { method: "POST" }),
  whatsappScanStatus: () => request<{ status: string }>("/whatsapp/scan/status"),
  whatsappMessages: (contactId: number) =>
    request<Array<{ id: number; body: string; direction: string; received_at: string }>>(`/whatsapp/messages?contact_id=${contactId}`),

  // Tags
  listTags: () => request<Tag[]>("/tags"),
  createTag: (name: string, color = "#6B7280") =>
    request<{ id: number; success: boolean }>("/tags", {
      method: "POST", body: JSON.stringify({ name, color }),
    }),
  deleteTag: (id: number) => request<{ success: boolean }>(`/tags/${id}`, { method: "DELETE" }),
  attachTag: (tagId: number, entityType: string, entityId: number) =>
    request<{ success: boolean }>(`/tags/${tagId}/attach`, {
      method: "POST", body: JSON.stringify({ entity_type: entityType, entity_id: entityId }),
    }),
  detachTag: (tagId: number, entityType: string, entityId: number) =>
    request<{ success: boolean }>(`/tags/${tagId}/detach`, {
      method: "POST", body: JSON.stringify({ entity_type: entityType, entity_id: entityId }),
    }),
  getEntityTags: (entityType: string, entityId: number) =>
    request<Tag[]>(`/tags/entity/${entityType}/${entityId}`),

  // Inbox
  getInbox: (params?: { channel?: string; page?: number }) => {
    const p = new URLSearchParams();
    if (params?.channel) p.set("channel", params.channel);
    if (params?.page) p.set("page", String(params.page));
    return request<InboxResponse>(`/inbox?${p}`);
  },
};
