export interface CampaignMessage {
  id: number;
  contact_name: string;
  event_type: string;
  template_subject: string | null;
  sent_at: string;
  reply_status: string;
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

export interface CampaignResponse extends Campaign {}

export interface CampaignListResponse {
  campaigns: Campaign[];
}
