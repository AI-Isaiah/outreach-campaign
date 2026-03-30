export interface CampaignMessage {
  id: number;
  contact_name: string;
  event_type: string;
  template_subject: string | null;
  sent_at: string;
  reply_status: string;
}

export interface MessageDraft {
  draft_subject: string | null;
  draft_text: string;
  channel: string;
  model: string;
  generated_at: string;
  research_id: number | null;
}

export interface QueueItem {
  contact_id: number;
  contact_name: string;
  company_name: string;
  company_id: number;
  aum_millions: number | null;
  firm_type: string | null;
  aum_tier: string;
  channel: string;
  step_order: number;
  total_steps: number;
  template_id: number | null;
  is_gdpr: boolean;
  email: string | null;
  linkedin_url: string | null;
  rendered_email?: RenderedEmail | null;
  rendered_message?: string | null;
  sales_nav_url?: string;
  gmail_draft?: { draft_id: string; status: string } | null;
  // Cross-campaign queue fields (added by /queue/all)
  campaign_name?: string;
  campaign_id?: number;
  // Adaptive engine fields (Phase 3)
  priority_score?: number;
  selection_mode?: string;
  reasoning?: string;
  // Phase 4: AI draft fields
  message_draft?: MessageDraft | null;
  has_research?: boolean;
  draft_mode?: 'template' | 'ai';
  fund_signals?: FundSignal[];
}

export interface FundSignal {
  type: string;
  text: string;
  recency_score: number;
}

export interface RenderedEmail {
  subject: string;
  body_text: string;
  body_html: string;
  contact_email: string;
  template_id: number;
}

export interface QueueResponse {
  campaign: string;
  campaign_id: number;
  date: string | null;
  items: QueueItem[];
  total: number;
  firm_type_counts: Record<string, number>;
}

export interface Campaign {
  id: number;
  name: string;
  description: string | null;
  status: string;
  created_at: string;
  health_score?: number | null;
}

export interface ReplyBreakdown {
  positive: number;
  negative: number;
  total: number;
  positive_rate: number;
}

export interface CampaignMetrics {
  total_enrolled: number;
  by_status: Record<string, number>;
  emails_sent: number;
  linkedin_connects: number;
  linkedin_messages: number;
  calls_booked: number;
  reply_rate: number;
  positive_rate: number;
  reply_breakdown: ReplyBreakdown;
}

export interface TemplatePerformanceItem {
  template_id: number;
  template_name: string;
  channel: string;
  total_sends: number;
  positive: number;
  negative: number;
  pending: number;
  positive_rate: number;
  confidence: string;
  is_winning: boolean;
}

export interface VariantComparison {
  variant: string;
  total: number;
  replied_positive: number;
  replied_negative: number;
  no_response: number;
  reply_rate: number;
  positive_rate: number;
}

export interface WeeklySummary {
  period: string;
  emails_sent: number;
  linkedin_actions: number;
  replies_positive: number;
  replies_negative: number;
  calls_booked: number;
  new_no_response: number;
}

export interface FirmBreakdown {
  firm_type: string;
  total: number;
  replied_positive: number;
  replied_negative: number;
  no_response: number;
  reply_rate: number;
  positive_rate: number;
}

export interface CampaignMetricsResponse {
  campaign: Campaign;
  metrics: CampaignMetrics;
  variants: VariantComparison[];
  weekly: WeeklySummary;
  firm_breakdown: FirmBreakdown[];
}

export interface Contact {
  id: number;
  company_id: number | null;
  first_name: string | null;
  last_name: string | null;
  full_name: string | null;
  email: string | null;
  email_normalized: string | null;
  email_status: string;
  linkedin_url: string | null;
  linkedin_url_normalized: string | null;
  title: string | null;
  priority_rank: number;
  source: string;
  is_gdpr: number;
  unsubscribed: number;
  lifecycle_stage: string;
  newsletter_status?: string | null;
  phone_number?: string | null;
  phone_normalized?: string | null;
  company_name?: string;
  aum_millions?: number | null;
  firm_type?: string | null;
  country?: string | null;
  campaign_status?: string | null;
}

export interface ContactListResponse {
  contacts: Contact[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface Enrollment {
  id: number;
  contact_id: number;
  campaign_id: number;
  campaign_name: string;
  current_step: number;
  status: string;
  assigned_variant: string | null;
  next_action_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface ContactEvent {
  id: number;
  contact_id: number;
  campaign_id: number | null;
  event_type: string;
  template_id: number | null;
  template_name: string | null;
  metadata: string | null;
  created_at: string;
}

export interface ContactDetailResponse {
  contact: Contact;
  enrollments: Enrollment[];
  notes: ResponseNote[];
}

export interface ResponseNote {
  id: number;
  contact_id: number;
  campaign_id: number | null;
  note_type: string;
  content: string;
  created_at: string;
}

export interface DbStats {
  companies: number;
  contacts: number;
  with_email: number;
  with_linkedin: number;
  gdpr: number;
  email_status: {
    verified: number;
    invalid: number;
    unverified: number;
  };
  campaigns: number;
  enrolled: number;
  events: number;
}

// --- Phase 2 new types ---

export interface Template {
  id: number;
  name: string;
  channel: string;
  subject: string | null;
  body_template: string;
  variant_group: string | null;
  variant_label: string | null;
  is_active: number;
  created_at: string;
}

export interface PendingReply {
  id: number;
  contact_id: number;
  campaign_id: number | null;
  gmail_thread_id: string | null;
  gmail_message_id: string | null;
  subject: string | null;
  snippet: string | null;
  classification: string | null;
  confidence: number | null;
  confirmed: number;
  confirmed_outcome: string | null;
  detected_at: string;
  confirmed_at: string | null;
  contact_name: string;
  contact_email: string;
  company_name: string | null;
  aum_millions: number | null;
}

export interface TimelineEntry {
  contact_id: number;
  campaign_id: number | null;
  source: string;
  interaction_type: string;
  subject: string | null;
  body: string | null;
  metadata: string | null;
  occurred_at: string;
}

export interface TimelineResponse {
  entries: TimelineEntry[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface Company {
  id: number;
  name: string;
  name_normalized: string;
  address: string | null;
  city: string | null;
  country: string | null;
  aum_millions: number | null;
  firm_type: string | null;
  website: string | null;
  linkedin_url: string | null;
  is_gdpr: number;
  contact_count?: number;
  enrolled_count?: number;
  positive_replies?: number;
}

export interface CompanyDetailResponse {
  company: Company;
  contacts: Contact[];
  event_count: number;
}

export interface SearchResults {
  contacts: Array<{
    id: number;
    full_name: string | null;
    email: string | null;
    company_name: string | null;
    result_type: "contact";
  }>;
  companies: Array<{
    id: number;
    name: string;
    firm_type: string | null;
    aum_millions: number | null;
    result_type: "company";
  }>;
  messages: Array<{
    id: number;
    contact_id: number;
    content: string;
    contact_name: string;
    result_type: "note";
  }>;
  total: number;
}

export interface EngineSettings {
  engine_config: Record<string, string>;
  gmail_authorized: boolean;
}

// --- Round 3: CRM Pipeline, Tags, Inbox ---

export interface Deal {
  id: number;
  company_id: number;
  contact_id: number | null;
  campaign_id: number | null;
  title: string;
  stage: string;
  amount_millions: number | null;
  expected_close_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  company_name?: string;
  aum_millions?: number | null;
  contact_name?: string | null;
  contact_email?: string | null;
}

export interface DealPipeline {
  pipeline: Record<string, Deal[]>;
}

export interface Tag {
  id: number;
  name: string;
  color: string;
  created_at: string;
}

export interface InboxItem {
  item_id: number;
  channel: "email" | "note";
  contact_name: string | null;
  company_name: string | null;
  contact_id: number;
  company_id: number | null;
  subject: string | null;
  body: string | null;
  classification: string | null;
  occurred_at: string;
}

export interface InboxResponse {
  items: InboxItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

// --- API Response Types ---

export interface StatsResponse extends DbStats {}

export interface CampaignResponse extends Campaign {}

export interface DealResponse {
  deal: Deal;
  stage_history: Array<{
    id: number;
    deal_id: number;
    from_stage: string | null;
    to_stage: string;
    changed_at: string;
  }>;
}

export interface LinkedInScanResponse {
  scanned: number;
  matched: number;
  advanced: number;
  already_processed: number;
  details: Array<{
    contact_id: number;
    contact_name: string;
    match_method: "linkedin_url" | "name";
    advanced: boolean;
  }>;
}

export interface ReplyScanResponse {
  scanned: number;
  new_replies: number;
}

export interface PendingRepliesResponse {
  replies: PendingReply[];
  last_auto_scan_at: string | null;
}

export interface ImportResponse {
  message: string;
  deduped: number;
  remaining: number;
}

export interface CampaignListResponse {
  campaigns: Campaign[];
}

export interface CompanyListResponse {
  companies: Company[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface DealListResponse {
  deals: Deal[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface AnalysisResponse {
  id: number;
  campaign_id: number;
  insights: string[];
  template_suggestions: string[];
  strategy_notes: string;
  insights_json?: string;
  created_at: string;
}

export interface BatchValidationErrors {
  error: string;
  company_duplicates?: { company_id: number; company_name: string; count: number }[];
  email_duplicates?: { email: string; count: number }[];
}

export interface DeferStatsResponse {
  today_count: number;
  total_count: number;
  by_reason: Array<{ reason: string; count: number }>;
  repeat_deferrals: Array<{
    contact_id: number;
    contact_name: string;
    defer_count: number;
  }>;
}

// --- CRM Extensions ---

export interface Product {
  id: number;
  name: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
}

export interface ContactProduct {
  id: number;
  contact_id: number;
  product_id: number;
  stage: string;
  notes: string | null;
  product_name: string;
  product_description: string | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: number;
  contact_id: number;
  channel: string;
  title: string;
  notes: string | null;
  outcome: string | null;
  occurred_at: string;
  created_at: string;
}

export interface Newsletter {
  id: number;
  subject: string;
  body_html: string;
  body_text: string | null;
  status: string;
  sent_at: string | null;
  recipient_count: number;
  created_at: string;
  updated_at: string;
}

export interface NewsletterAttachment {
  id: number;
  newsletter_id: number;
  filename: string;
  content_type: string;
  file_path: string;
  file_size_bytes: number | null;
  created_at: string;
}

export interface NewsletterDetail {
  newsletter: Newsletter;
  attachments: NewsletterAttachment[];
  send_stats: Record<string, number>;
}

export interface NewsletterListResponse {
  newsletters: Newsletter[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface RecipientPreview {
  recipients: Array<{
    id: number;
    full_name: string | null;
    email: string;
    first_name: string | null;
    last_name: string | null;
    lifecycle_stage: string;
    company_name: string | null;
  }>;
  count: number;
}

// --- Crypto Research Pipeline ---

export const TERMINAL_STATUSES = ["completed", "failed", "cancelled", "cancelling"] as const;
export function isTerminalStatus(s: string): boolean {
  return (TERMINAL_STATUSES as readonly string[]).includes(s);
}

export interface ResearchJob {
  id: number;
  name: string;
  status: "pending" | "researching" | "classifying" | "completed" | "failed" | "cancelling" | "cancelled";
  method: "web_search" | "website_crawl" | "hybrid";
  total_companies: number;
  processed_companies: number;
  classified_companies: number;
  contacts_discovered: number;
  error_message: string | null;
  cost_estimate_usd: number | null;
  actual_cost_usd: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ResearchResult {
  id: number;
  job_id: number;
  company_id: number | null;
  company_name: string;
  company_website: string | null;
  web_search_raw: string | null;
  website_crawl_raw: string | null;
  crypto_score: number | null;
  category: "confirmed_investor" | "likely_interested" | "possible" | "no_signal" | "unlikely" | null;
  evidence_summary: string | null;
  evidence_json: Array<{ source: string; quote: string; relevance: string }> | null;
  classification_reasoning: string | null;
  discovered_contacts_json: Array<{
    name: string;
    title: string;
    email: string | null;
    linkedin: string | null;
    source: string;
  }> | null;
  warm_intro_contact_ids: number[] | null;
  warm_intro_notes: string | null;
  status: "pending" | "researching" | "classified" | "completed" | "error";
  created_at: string;
  updated_at?: string;
}

export interface ResearchJobDetail {
  job: ResearchJob;
  by_category: Record<string, number>;
  score_distribution: Array<{ range: string; count: number }>;
  avg_score: number;
  max_score: number;
  min_score: number;
  warm_intro_count: number;
  with_contacts: number;
  total_contacts_discovered: number;
  error_count: number;
}

export interface CsvPreview {
  total_rows: number;
  preview: Array<{
    company_name: string;
    website?: string;
    country?: string;
    aum?: string;
    firm_type?: string;
  }>;
  raw_headers: string[];
  mapped_headers: Record<string, string>;
  stats: {
    with_website: number;
    with_country: number;
    with_aum: number;
  };
}

export interface BatchImportResponse {
  success: boolean;
  imported_contacts: number;
  deals_created: number;
  enrolled: number;
  skipped_duplicates: number;
  results_processed: number;
}

export interface ResearchJobsResponse {
  jobs: ResearchJob[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface ResearchResultsResponse {
  results: ResearchResult[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface ResearchCostEstimate {
  web_search_cost: number;
  crawl_cost: number;
  llm_cost: number;
  contact_discovery_cost: number;
  total: number;
}

export interface CreateResearchJobResponse {
  job_id: number;
  total_companies: number;
  cost_estimate: ResearchCostEstimate;
  status: string;
  warnings: string[];
  duplicates_skipped: number;
}
