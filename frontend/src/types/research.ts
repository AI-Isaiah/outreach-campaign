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

export interface BatchImportResponse {
  success: boolean;
  imported_contacts: number;
  deals_created: number;
  enrolled: number;
  skipped_duplicates: number;
  results_processed: number;
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
