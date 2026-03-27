import type { ContactListResponse, ContactDetailResponse, ContactEvent, Conversation } from "../types";
import { request } from "./request";

export const contactsApi = {
  listContacts: (
    page = 1,
    search?: string,
    options?: {
      per_page?: number;
      sort_by?: "name" | "company" | "aum";
      sort_dir?: "asc" | "desc";
      has_linkedin?: boolean;
      has_email?: boolean;
      one_per_company?: boolean;
    },
  ) => {
    const params = new URLSearchParams({
      page: String(page),
      per_page: String(options?.per_page ?? 50),
    });
    if (search) params.set("search", search);
    if (options?.sort_by) params.set("sort_by", options.sort_by);
    if (options?.sort_dir) params.set("sort_dir", options.sort_dir);
    if (options?.has_linkedin) params.set("has_linkedin", "true");
    if (options?.has_email) params.set("has_email", "true");
    if (options?.one_per_company) params.set("one_per_company", "true");
    return request<ContactListResponse>(`/contacts?${params}`);
  },
  getContact: (id: number) => request<ContactDetailResponse>(`/contacts/${id}`),
  getContactEvents: (id: number) => request<ContactEvent[]>(`/contacts/${id}/events`),

  updateContactStatus: (id: number, campaign: string, newStatus: string, note?: string) =>
    request<{ success: boolean }>(`/contacts/${id}/status`, {
      method: "POST", body: JSON.stringify({ campaign, new_status: newStatus, note }),
    }),

  addNote: (id: number, content: string, noteType = "general", campaign?: string) =>
    request<{ success: boolean }>(`/contacts/${id}/notes`, {
      method: "POST", body: JSON.stringify({ content, note_type: noteType, campaign }),
    }),

  updatePhone: (id: number, phoneNumber: string) =>
    request<{ success: boolean }>(`/contacts/${id}/phone`, {
      method: "POST", body: JSON.stringify({ phone_number: phoneNumber }),
    }),

  updateLinkedInUrl: (id: number, linkedinUrl: string) =>
    request<{ success: boolean }>(`/contacts/${id}/linkedin-url`, {
      method: "POST", body: JSON.stringify({ linkedin_url: linkedinUrl }),
    }),

  updateContactName: (id: number, firstName: string, lastName: string) =>
    request<{ success: boolean }>(`/contacts/${id}/name`, {
      method: "POST", body: JSON.stringify({ first_name: firstName, last_name: lastName }),
    }),

  patchContact: (id: number, fields: {
    first_name?: string; last_name?: string; email?: string;
    linkedin_url?: string; title?: string;
  }) =>
    request<{ success: boolean; contact: any }>(`/contacts/${id}`, {
      method: "PATCH", body: JSON.stringify(fields),
    }),

  createContact: (data: {
    first_name: string; last_name: string; email?: string; phone_number?: string;
    linkedin_url?: string; title?: string; company_id?: number;
    lifecycle_stage?: string; newsletter_opt_in?: boolean; notes?: string;
  }) =>
    request<{ id: number; success: boolean }>("/contacts", {
      method: "POST", body: JSON.stringify(data),
    }),

  updateLifecycle: (id: number, lifecycleStage: string) =>
    request<{ success: boolean }>(`/contacts/${id}/lifecycle`, {
      method: "PATCH", body: JSON.stringify({ lifecycle_stage: lifecycleStage }),
    }),

  bulkUpdateLifecycle: (contactIds: number[], lifecycleStage: string) =>
    request<{ success: boolean; updated: number }>("/contacts/bulk/lifecycle", {
      method: "POST", body: JSON.stringify({ contact_ids: contactIds, lifecycle_stage: lifecycleStage }),
    }),

  listConversations: (contactId: number) =>
    request<Conversation[]>(`/contacts/${contactId}/conversations`),

  createConversation: (contactId: number, data: {
    channel: string; title: string; notes?: string; outcome?: string; occurred_at?: string;
  }) =>
    request<{ id: number; success: boolean }>(`/contacts/${contactId}/conversations`, {
      method: "POST", body: JSON.stringify(data),
    }),

  updateConversation: (id: number, data: Partial<Conversation>) =>
    request<{ success: boolean }>(`/conversations/${id}`, {
      method: "PUT", body: JSON.stringify(data),
    }),

  deleteConversation: (id: number) =>
    request<{ success: boolean }>(`/conversations/${id}`, { method: "DELETE" }),
};
