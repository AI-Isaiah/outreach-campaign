import { request } from "./request";

export interface EmailConfig {
  gmail_connected: boolean;
  gmail_email: string | null;
  smtp_configured: boolean;
  smtp_host: string | null;
  smtp_from_email: string | null;
  smtp_from_name: string | null;
  physical_address: string | null;
  calendly_url: string | null;
}

export async function getEmailConfig(): Promise<EmailConfig> {
  return request<EmailConfig>("/settings/email-config");
}

export async function saveSmtpConfig(config: {
  host: string;
  port: number;
  username: string;
  password: string;
  use_tls: boolean;
  from_email: string;
  from_name: string;
}): Promise<{ success: boolean }> {
  return request<{ success: boolean }>("/settings/smtp", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function saveComplianceConfig(config: {
  physical_address: string;
  calendly_url: string;
}): Promise<{ success: boolean }> {
  return request<{ success: boolean }>("/settings/compliance", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function disconnectGmail(): Promise<{ success: boolean }> {
  return request<{ success: boolean }>("/auth/gmail/disconnect", {
    method: "POST",
    body: JSON.stringify({}),
  });
}
