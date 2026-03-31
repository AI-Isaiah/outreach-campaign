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

export interface DealListResponse {
  deals: Deal[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
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

export interface Product {
  id: number;
  name: string;
  description: string | null;
  is_active: boolean;
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
