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
