export interface QueueItem {
  contact_id: number;
  contact_name: string;
  company_name: string;
  company_id: number;
  aum_millions: number | null;
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
  // Adaptive engine fields (Phase 3)
  priority_score?: number;
  selection_mode?: string;
  reasoning?: string;
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
}

export interface Campaign {
  id: number;
  name: string;
  description: string | null;
  status: string;
  created_at: string;
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
  company_id: number;
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
  phone_number?: string | null;
  phone_normalized?: string | null;
  company_name?: string;
  aum_millions?: number | null;
  firm_type?: string | null;
  country?: string | null;
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
  whatsapp_status: string;
}
