import type {
  SearchResults,
  EngineSettings,
  Template,
  PendingReply,
  TimelineResponse,
  CompanyDetailResponse,
} from "../types";

const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  // Queue
  getQueue: (campaign: string, date?: string, limit = 20) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (date) params.set("date", date);
    return request<any>(`/queue/${campaign}?${params}`);
  },

  markLinkedInDone: (contactId: number, actionType: string, campaign: string) =>
    request<any>(`/queue/${contactId}/linkedin-done?campaign=${campaign}`, {
      method: "POST",
      body: JSON.stringify({ action_type: actionType }),
    }),

  overrideTemplate: (campaign: string, contactId: number, templateId: number) =>
    request<any>(`/queue/${campaign}/override`, {
      method: "POST",
      body: JSON.stringify({ contact_id: contactId, template_id: templateId }),
    }),

  // Campaigns
  listCampaigns: () => request<any[]>("/campaigns"),
  getCampaign: (name: string) => request<any>(`/campaigns/${name}`),
  getCampaignMetrics: (name: string) => request<any>(`/campaigns/${name}/metrics`),
  getCampaignWeekly: (name: string, weeksBack = 1) =>
    request<any>(`/campaigns/${name}/weekly?weeks_back=${weeksBack}`),
  getCampaignReport: (name: string) => request<any>(`/campaigns/${name}/report`),

  // Contacts
  listContacts: (page = 1, search?: string) => {
    const params = new URLSearchParams({ page: String(page), per_page: "50" });
    if (search) params.set("search", search);
    return request<any>(`/contacts?${params}`);
  },
  getContact: (id: number) => request<any>(`/contacts/${id}`),
  getContactEvents: (id: number) => request<any[]>(`/contacts/${id}/events`),

  updateContactStatus: (id: number, campaign: string, newStatus: string, note?: string) =>
    request<any>(`/contacts/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ campaign, new_status: newStatus, note }),
    }),

  addNote: (id: number, content: string, noteType = "general", campaign?: string) =>
    request<any>(`/contacts/${id}/notes`, {
      method: "POST",
      body: JSON.stringify({ content, note_type: noteType, campaign }),
    }),

  updatePhone: (id: number, phoneNumber: string) =>
    request<any>(`/contacts/${id}/phone`, {
      method: "POST",
      body: JSON.stringify({ phone_number: phoneNumber }),
    }),

  // Stats
  getStats: () => request<any>("/stats"),

  // Gmail
  getGmailStatus: () => request<any>("/gmail/status"),
  authorizeGmail: () => request<any>("/gmail/authorize", { method: "POST" }),
  createDraft: (contactId: number, campaign: string, templateId: number, subject?: string, bodyText?: string) =>
    request<any>("/gmail/drafts", {
      method: "POST",
      body: JSON.stringify({ contact_id: contactId, campaign, template_id: templateId, subject, body_text: bodyText }),
    }),
  createBatchDrafts: (campaign: string, date?: string) =>
    request<any>("/gmail/drafts/batch", {
      method: "POST",
      body: JSON.stringify({ campaign, date }),
    }),
  checkDraftStatus: (contactId: number, campaign: string) =>
    request<any>(`/gmail/drafts/${contactId}?campaign=${campaign}`),

  // Templates
  listTemplates: (channel?: string, active = true) => {
    const params = new URLSearchParams({ active: String(active) });
    if (channel) params.set("channel", channel);
    return request<Template[]>(`/templates?${params}`);
  },
  getTemplate: (id: number) => request<Template>(`/templates/${id}`),
  createTemplate: (data: {
    name: string;
    channel: string;
    body_template: string;
    subject?: string;
    variant_group?: string;
    variant_label?: string;
  }) =>
    request<{ id: number; success: boolean }>("/templates", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateTemplate: (id: number, data: Partial<Template>) =>
    request<any>(`/templates/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  deactivateTemplate: (id: number) =>
    request<any>(`/templates/${id}/deactivate`, { method: "PATCH" }),

  // Pending Replies
  listPendingReplies: () => request<PendingReply[]>("/replies/pending"),
  confirmReply: (id: number, outcome: string, note?: string) =>
    request<any>(`/replies/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify({ outcome, note }),
    }),
  scanReplies: () => request<any>("/replies/scan", { method: "POST" }),

  // CRM
  listCrmContacts: (params?: {
    search?: string;
    status?: string;
    company_type?: string;
    min_aum?: number;
    max_aum?: number;
    page?: number;
  }) => {
    const p = new URLSearchParams();
    if (params?.search) p.set("search", params.search);
    if (params?.status) p.set("status", params.status);
    if (params?.company_type) p.set("company_type", params.company_type);
    if (params?.min_aum != null) p.set("min_aum", String(params.min_aum));
    if (params?.max_aum != null) p.set("max_aum", String(params.max_aum));
    if (params?.page) p.set("page", String(params.page));
    return request<any>(`/crm/contacts?${p}`);
  },

  getContactTimeline: (id: number, page = 1) =>
    request<TimelineResponse>(`/crm/contacts/${id}/timeline?page=${page}`),

  listCompanies: (params?: { search?: string; firm_type?: string; page?: number }) => {
    const p = new URLSearchParams();
    if (params?.search) p.set("search", params.search);
    if (params?.firm_type) p.set("firm_type", params.firm_type);
    if (params?.page) p.set("page", String(params.page));
    return request<any>(`/crm/companies?${p}`);
  },

  getCompany: (id: number) => request<CompanyDetailResponse>(`/crm/companies/${id}`),

  globalSearch: (q: string) => request<SearchResults>(`/crm/search?q=${encodeURIComponent(q)}`),

  // Settings
  getSettings: () => request<EngineSettings>("/settings"),
  updateSettings: (settings: Record<string, string>) =>
    request<any>("/settings", {
      method: "PUT",
      body: JSON.stringify({ settings }),
    }),

  // Import
  runDedupe: () => request<any>("/import/dedupe", { method: "POST" }),

  // Insights
  runAnalysis: (campaignId: number) =>
    request<any>("/insights/analyze", {
      method: "POST",
      body: JSON.stringify({ campaign_id: campaignId }),
    }),
  getInsightHistory: () => request<any[]>("/insights/history"),

  // WhatsApp
  whatsappSetup: () => request<any>("/whatsapp/setup", { method: "POST" }),
  whatsappScan: () => request<any>("/whatsapp/scan", { method: "POST" }),
  whatsappScanStatus: () => request<any>("/whatsapp/scan/status"),
  whatsappMessages: (contactId: number) =>
    request<any[]>(`/whatsapp/messages?contact_id=${contactId}`),
};
