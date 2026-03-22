/**
 * Re-exports the combined `api` object for backward compatibility.
 * New code can import domain modules directly (e.g. `import { queueApi } from "../api/queue"`).
 */
export { api } from "./client";
export { request, BASE } from "./request";

export { queueApi } from "./queue";
export { campaignsApi } from "./campaigns";
export { contactsApi } from "./contacts";
export { dealsApi } from "./deals";
export { newslettersApi } from "./newsletters";
export { researchApi } from "./research";
export { getEmailConfig, saveSmtpConfig, saveComplianceConfig, disconnectGmail } from "./settings";
export type { EmailConfig } from "./settings";
