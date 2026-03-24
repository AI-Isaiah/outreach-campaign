import { BASE, authHeaders, request } from "./request";

export interface AnalyzeResult {
  import_job_id: string;
  headers: string[];
  proposed_mapping: Record<string, string>;
  sample_rows: Record<string, string>[];
  multi_contact: {
    detected: boolean;
    contact_groups?: Array<{
      prefix: string;
      fields: Record<string, string>;
    }>;
  };
  confidence: number;
  row_count: number;
}

export interface ExistingContact {
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  title: string | null;
  linkedin_url: string | null;
  company_name: string | null;
}

export interface PreviewRow {
  _index: number;
  company_name: string;
  full_name: string | null;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  email_normalized: string | null;
  title: string | null;
  linkedin_url: string | null;
  country: string | null;
  aum_millions: number | null;
  firm_type: string | null;
  is_gdpr: boolean;
  is_duplicate: boolean;
  duplicate_type: "exact" | "email_overlap" | "linkedin_overlap" | "both_overlap" | null;
  overlap_cleared: "email" | "linkedin" | "email+linkedin" | null;
  existing_contact: ExistingContact | null;
  [key: string]: unknown;
}

export interface PreviewResult {
  total_contacts: number;
  total_companies: number;
  duplicates: number;
  new_contacts: number;
  preview_rows: PreviewRow[];
}

export interface ImportResult {
  companies_created: number;
  contacts_created: number;
  duplicates_skipped: number;
}

export const smartImportApi = {
  analyze: async (file: File): Promise<AnalyzeResult> => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${BASE}/import/smart`, {
      method: "POST",
      headers: authHeaders(),
      body: formData,
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  preview: async (
    jobId: string,
    mapping: Record<string, string>,
    sourceLabel?: string,
  ): Promise<PreviewResult> =>
    request<PreviewResult>("/import/preview", {
      method: "POST",
      body: JSON.stringify({
        import_job_id: jobId,
        approved_mapping: mapping,
        source_label: sourceLabel,
      }),
    }),

  execute: async (jobId: string, excludedIndices?: number[]): Promise<ImportResult> =>
    request<ImportResult>("/import/execute", {
      method: "POST",
      body: JSON.stringify({
        import_job_id: jobId,
        excluded_indices: excludedIndices?.length ? excludedIndices : undefined,
      }),
    }),
};
