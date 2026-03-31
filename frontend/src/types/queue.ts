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

export interface QueueResponse {
  campaign: string;
  campaign_id: number;
  date: string | null;
  items: QueueItem[];
  total: number;
  total_enrolled?: number;
  firm_type_counts: Record<string, number>;
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
