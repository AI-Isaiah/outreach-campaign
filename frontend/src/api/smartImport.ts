import { BASE, authHeaders, request } from "./request";

export interface AnalyzeResult {
  import_job_id: string;
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

export interface PreviewResult {
  total_contacts: number;
  total_companies: number;
  duplicates: number;
  new_contacts: number;
  preview_rows: Record<string, string>[];
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

  execute: async (jobId: string): Promise<ImportResult> =>
    request<ImportResult>("/import/execute", {
      method: "POST",
      body: JSON.stringify({ import_job_id: jobId }),
    }),
};
