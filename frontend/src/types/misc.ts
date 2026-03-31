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

// --- API Response Types ---

export interface StatsResponse extends DbStats {}

export interface PendingRepliesResponse {
  replies: PendingReply[];
  last_auto_scan_at: string | null;
}

export interface ImportResponse {
  message: string;
  deduped: number;
  remaining: number;
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
