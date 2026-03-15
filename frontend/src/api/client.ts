import type {
  SearchResults,
  EngineSettings,
  Template,
  PendingReply,
  TimelineResponse,
  CompanyDetailResponse,
  Campaign,
  Deal,
  DealPipeline,
  Tag,
  InboxResponse,
  StatsResponse,
  CampaignResponse,
  ContactDetailResponse,
  DealResponse,
  LinkedInScanResponse,
  ReplyScanResponse,
  ImportResponse,
  CampaignListResponse,
  ContactListResponse,
  CompanyListResponse,
  DealListResponse,
  AnalysisResponse,
  DeferStatsResponse,
  QueueResponse,
  Product,
  ContactProduct,
  Conversation,
  NewsletterDetail,
  NewsletterListResponse,
  RecipientPreview,
  CreateResearchJobResponse,
  CsvPreview,
  ResearchJobDetail,
  ResearchJobsResponse,
  ResearchResult,
  ResearchResultsResponse,
  BatchImportResponse,
} from "../types";

const BASE = import.meta.env.VITE_API_BASE_URL || "/api";

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
  getQueue: (campaign: string, options?: {
    date?: string;
    limit?: number;
    firm_type?: string;
    aum_min?: number;
    aum_max?: number;
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
      method: "POST",
      body: JSON.stringify({ action_type: actionType }),
    }),

  overrideTemplate: (campaign: string, contactId: number, templateId: number) =>
    request<{ success: boolean }>(`/queue/${campaign}/override`, {
      method: "POST",
      body: JSON.stringify({ contact_id: contactId, template_id: templateId }),
    }),

  deferContact: (contactId: number, campaign: string, reason?: string) =>
    request<{ success: boolean }>(`/queue/${contactId}/defer`, {
      method: "POST",
      body: JSON.stringify({ campaign, reason }),
    }),

  getDeferStats: (campaign?: string) => {
    const params = new URLSearchParams();
    if (campaign) params.set("campaign", campaign);
    return request<DeferStatsResponse>(`/queue/defer/stats?${params}`);
  },

  // Campaigns
  listCampaigns: () => request<Campaign[]>("/campaigns"),
  createCampaign: (data: { name: string; description?: string; status?: string }) =>
    request<{ id: number; success: boolean }>("/campaigns", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getCampaign: (name: string) => request<CampaignResponse>(`/campaigns/${name}`),
  getCampaignMetrics: (name: string) => request<import("../types").CampaignMetricsResponse>(`/campaigns/${name}/metrics`),
  getCampaignWeekly: (name: string, weeksBack = 1) =>
    request<{ weekly: import("../types").WeeklySummary }>(`/campaigns/${name}/weekly?weeks_back=${weeksBack}`),
  getCampaignReport: (name: string) => request<{ report: string }>(`/campaigns/${name}/report`),

  // Contacts
  listContacts: (page = 1, search?: string) => {
    const params = new URLSearchParams({ page: String(page), per_page: "50" });
    if (search) params.set("search", search);
    return request<ContactListResponse>(`/contacts?${params}`);
  },
  getContact: (id: number) => request<ContactDetailResponse>(`/contacts/${id}`),
  getContactEvents: (id: number) => request<import("../types").ContactEvent[]>(`/contacts/${id}/events`),

  updateContactStatus: (id: number, campaign: string, newStatus: string, note?: string) =>
    request<{ success: boolean }>(`/contacts/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ campaign, new_status: newStatus, note }),
    }),

  addNote: (id: number, content: string, noteType = "general", campaign?: string) =>
    request<{ success: boolean }>(`/contacts/${id}/notes`, {
      method: "POST",
      body: JSON.stringify({ content, note_type: noteType, campaign }),
    }),

  updatePhone: (id: number, phoneNumber: string) =>
    request<{ success: boolean }>(`/contacts/${id}/phone`, {
      method: "POST",
      body: JSON.stringify({ phone_number: phoneNumber }),
    }),

  updateLinkedInUrl: (id: number, linkedinUrl: string) =>
    request<{ success: boolean }>(`/contacts/${id}/linkedin-url`, {
      method: "POST",
      body: JSON.stringify({ linkedin_url: linkedinUrl }),
    }),

  updateContactName: (id: number, firstName: string, lastName: string) =>
    request<{ success: boolean }>(`/contacts/${id}/name`, {
      method: "POST",
      body: JSON.stringify({ first_name: firstName, last_name: lastName }),
    }),

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
      method: "POST",
      body: JSON.stringify({ campaign, date }),
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
    request<{ success: boolean }>(`/templates/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  deactivateTemplate: (id: number) =>
    request<{ success: boolean }>(`/templates/${id}/deactivate`, { method: "PATCH" }),

  // Pending Replies
  listPendingReplies: () => request<PendingReply[]>("/replies/pending"),
  confirmReply: (id: number, outcome: string, note?: string) =>
    request<{ success: boolean }>(`/replies/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify({ outcome, note }),
    }),
  scanReplies: () => request<ReplyScanResponse>("/replies/scan", { method: "POST" }),
  scanLinkedInAcceptances: () => request<LinkedInScanResponse>("/replies/scan-linkedin", { method: "POST" }),

  // Contacts — create & lifecycle
  createContact: (data: {
    first_name: string;
    last_name: string;
    email?: string;
    phone_number?: string;
    linkedin_url?: string;
    title?: string;
    company_id?: number;
    lifecycle_stage?: string;
    newsletter_opt_in?: boolean;
    notes?: string;
  }) =>
    request<{ id: number; success: boolean }>("/contacts", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  updateLifecycle: (id: number, lifecycleStage: string) =>
    request<{ success: boolean }>(`/contacts/${id}/lifecycle`, {
      method: "PATCH",
      body: JSON.stringify({ lifecycle_stage: lifecycleStage }),
    }),

  // Conversations
  listConversations: (contactId: number) =>
    request<Conversation[]>(`/contacts/${contactId}/conversations`),

  createConversation: (contactId: number, data: {
    channel: string;
    title: string;
    notes?: string;
    outcome?: string;
    occurred_at?: string;
  }) =>
    request<{ id: number; success: boolean }>(`/contacts/${contactId}/conversations`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  updateConversation: (id: number, data: Partial<Conversation>) =>
    request<{ success: boolean }>(`/conversations/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteConversation: (id: number) =>
    request<{ success: boolean }>(`/conversations/${id}`, { method: "DELETE" }),

  // Products
  listProducts: () => request<Product[]>("/products"),

  createProduct: (name: string, description?: string) =>
    request<{ id: number; success: boolean }>("/products", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),

  listContactProducts: (contactId: number) =>
    request<ContactProduct[]>(`/contacts/${contactId}/products`),

  linkContactProduct: (contactId: number, productId: number, stage = "discussed", notes?: string) =>
    request<{ id: number; success: boolean }>(`/contacts/${contactId}/products`, {
      method: "POST",
      body: JSON.stringify({ product_id: productId, stage, notes }),
    }),

  updateContactProductStage: (contactId: number, productId: number, stage: string) =>
    request<{ success: boolean }>(`/contacts/${contactId}/products/${productId}/stage`, {
      method: "PATCH",
      body: JSON.stringify({ stage }),
    }),

  removeContactProduct: (contactId: number, productId: number) =>
    request<{ success: boolean }>(`/contacts/${contactId}/products/${productId}`, { method: "DELETE" }),

  // Newsletters
  listNewsletters: (page = 1) =>
    request<NewsletterListResponse>(`/newsletters?page=${page}`),

  createNewsletter: (data: { subject: string; body_html: string; body_text?: string }) =>
    request<{ id: number; success: boolean }>("/newsletters", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getNewsletter: (id: number) => request<NewsletterDetail>(`/newsletters/${id}`),

  updateNewsletter: (id: number, data: { subject?: string; body_html?: string; body_text?: string }) =>
    request<{ success: boolean }>(`/newsletters/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteNewsletter: (id: number) =>
    request<{ success: boolean }>(`/newsletters/${id}`, { method: "DELETE" }),

  uploadNewsletterAttachment: async (newsletterId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${BASE}/newsletters/${newsletterId}/attachments`, {
      method: "POST",
      body: formData,
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
    lifecycle_stages?: string[];
    product_ids?: number[];
    newsletter_only?: boolean;
  }) => {
    const p = new URLSearchParams();
    if (params?.lifecycle_stages?.length) p.set("lifecycle_stages", params.lifecycle_stages.join(","));
    if (params?.product_ids?.length) p.set("product_ids", params.product_ids.join(","));
    if (params?.newsletter_only != null) p.set("newsletter_only", String(params.newsletter_only));
    return request<RecipientPreview>(`/newsletters/${newsletterId}/recipients?${p}`);
  },

  sendNewsletter: (id: number, data: {
    lifecycle_stages?: string[];
    product_ids?: number[];
    newsletter_only?: boolean;
  }) =>
    request<{ sent: number; failed: number; total: number }>(`/newsletters/${id}/send`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // CRM
  listCrmContacts: (params?: {
    search?: string;
    status?: string;
    company_type?: string;
    min_aum?: number;
    max_aum?: number;
    lifecycle_stage?: string;
    newsletter_subscriber?: boolean;
    product_id?: number;
    page?: number;
    sort_by?: string;
    sort_dir?: "asc" | "desc";
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

  listCompanies: (params?: { search?: string; firm_type?: string; page?: number }) => {
    const p = new URLSearchParams();
    if (params?.search) p.set("search", params.search);
    if (params?.firm_type) p.set("firm_type", params.firm_type);
    if (params?.page) p.set("page", String(params.page));
    return request<CompanyListResponse>(`/crm/companies?${p}`);
  },

  getCompany: (id: number) => request<CompanyDetailResponse>(`/crm/companies/${id}`),

  globalSearch: (q: string) => request<SearchResults>(`/crm/search?q=${encodeURIComponent(q)}`),

  // Settings
  getSettings: () => request<EngineSettings>("/settings"),
  updateSettings: (settings: Record<string, string>) =>
    request<{ success: boolean }>("/settings", {
      method: "PUT",
      body: JSON.stringify({ settings }),
    }),

  // Import
  runDedupe: () => request<ImportResponse>("/import/dedupe", { method: "POST" }),

  // Insights
  runAnalysis: (campaignId: number) =>
    request<AnalysisResponse>("/insights/analyze", {
      method: "POST",
      body: JSON.stringify({ campaign_id: campaignId }),
    }),
  getInsightHistory: () => request<AnalysisResponse[]>("/insights/history"),

  // WhatsApp
  whatsappSetup: () => request<{ success: boolean }>("/whatsapp/setup", { method: "POST" }),
  whatsappScan: () => request<{ scanned: number; success: boolean }>("/whatsapp/scan", { method: "POST" }),
  whatsappScanStatus: () => request<{ status: string }>("/whatsapp/scan/status"),
  whatsappMessages: (contactId: number) =>
    request<Array<{ id: number; body: string; direction: string; received_at: string }>>(`/whatsapp/messages?contact_id=${contactId}`),

  // Deals
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
  createDeal: (data: { company_id: number; contact_id?: number; campaign_id?: number; title: string; stage?: string; amount_millions?: number; notes?: string }) =>
    request<{ id: number; success: boolean }>("/deals", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getDeal: (id: number) => request<DealResponse>(`/deals/${id}`),
  updateDeal: (id: number, data: Partial<Deal>) =>
    request<{ success: boolean }>(`/deals/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  updateDealStage: (id: number, stage: string) =>
    request<{ success: boolean }>(`/deals/${id}/stage`, { method: "PATCH", body: JSON.stringify({ stage }) }),
  deleteDeal: (id: number) => request<{ success: boolean }>(`/deals/${id}`, { method: "DELETE" }),

  // Tags
  listTags: () => request<Tag[]>("/tags"),
  createTag: (name: string, color = "#6B7280") =>
    request<{ id: number; success: boolean }>("/tags", {
      method: "POST",
      body: JSON.stringify({ name, color }),
    }),
  deleteTag: (id: number) => request<{ success: boolean }>(`/tags/${id}`, { method: "DELETE" }),
  attachTag: (tagId: number, entityType: string, entityId: number) =>
    request<{ success: boolean }>(`/tags/${tagId}/attach`, {
      method: "POST",
      body: JSON.stringify({ entity_type: entityType, entity_id: entityId }),
    }),
  detachTag: (tagId: number, entityType: string, entityId: number) =>
    request<{ success: boolean }>(`/tags/${tagId}/detach`, {
      method: "POST",
      body: JSON.stringify({ entity_type: entityType, entity_id: entityId }),
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

  // Research
  previewResearchCsv: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${BASE}/research/preview-csv`, { method: "POST", body: formData });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }
    return res.json() as Promise<CsvPreview>;
  },

  createResearchJob: async (file: File, name: string, method = "hybrid", skipDuplicates = true) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("name", name);
    formData.append("method", method);
    formData.append("skip_duplicates", String(skipDuplicates));
    const res = await fetch(`${BASE}/research/jobs`, { method: "POST", body: formData });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }
    return res.json() as Promise<CreateResearchJobResponse>;
  },

  listResearchJobs: (status?: string, page = 1) => {
    const p = new URLSearchParams({ page: String(page) });
    if (status) p.set("status", status);
    return request<ResearchJobsResponse>(`/research/jobs?${p}`);
  },

  getResearchJob: (id: number) =>
    request<ResearchJobDetail>(`/research/jobs/${id}`),

  getResearchResults: (jobId: number, filters?: {
    category?: string;
    min_score?: number;
    has_warm_intros?: boolean;
    sort_by?: string;
    sort_dir?: string;
    page?: number;
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

  getResearchResult: (id: number) =>
    request<ResearchResult>(`/research/results/${id}`),

  importDiscoveredContacts: (resultId: number, indices: number[]) =>
    request<{ success: boolean; imported: number; company_id: number }>(
      `/research/results/${resultId}/import-contacts`,
      { method: "POST", body: JSON.stringify(indices) },
    ),

  batchImport: (resultIds: number[], createDeals = false, campaignName?: string) =>
    request<BatchImportResponse>(`/research/batch-import`, {
      method: "POST",
      body: JSON.stringify({
        result_ids: resultIds,
        create_deals: createDeals,
        campaign_name: campaignName,
      }),
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

  // Bulk actions
  bulkUpdateLifecycle: (contactIds: number[], lifecycleStage: string) =>
    request<{ success: boolean; updated: number }>("/contacts/bulk/lifecycle", {
      method: "POST",
      body: JSON.stringify({ contact_ids: contactIds, lifecycle_stage: lifecycleStage }),
    }),

  // Import
  importCsv: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${BASE}/import/csv`, { method: "POST", body: formData });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }
    return res.json() as Promise<{ imported: number; skipped: number; errors: string[] }>;
  },
};
