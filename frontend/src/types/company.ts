import type { Contact } from "./contact";

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

export interface CompanyListResponse {
  companies: Company[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}
