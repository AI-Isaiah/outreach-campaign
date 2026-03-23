/** Shared constants — single source of truth for labels, colors, and defaults. */

export const DEFAULT_CAMPAIGN = "Q1_2026_initial";

/** Contact campaign status → Tailwind classes */
export const STATUS_COLORS: Record<string, string> = {
  queued: "bg-gray-100 text-gray-700",
  in_progress: "bg-blue-100 text-blue-700",
  replied_positive: "bg-green-100 text-green-800",
  replied_negative: "bg-red-100 text-red-700",
  no_response: "bg-yellow-100 text-yellow-800",
  bounced: "bg-red-100 text-red-700",
  active: "bg-green-100 text-green-800",
  completed: "bg-gray-100 text-gray-700",
  drafted: "bg-blue-100 text-blue-700",
  sent: "bg-green-100 text-green-800",
  paused: "bg-amber-100 text-amber-700",
};

/** Lifecycle stages → Tailwind classes */
export const LIFECYCLE_COLORS: Record<string, string> = {
  cold: "bg-gray-100 text-gray-700",
  contacted: "bg-blue-100 text-blue-700",
  nurturing: "bg-amber-100 text-amber-700",
  client: "bg-green-100 text-green-800",
  churned: "bg-red-100 text-red-700",
};

export const LIFECYCLE_STAGES = ["cold", "contacted", "nurturing", "client", "churned"] as const;

/** Deal pipeline stages → Tailwind classes */
export const DEAL_STAGE_COLORS: Record<string, string> = {
  cold: "bg-gray-100 text-gray-700",
  contacted: "bg-blue-100 text-blue-700",
  engaged: "bg-indigo-100 text-indigo-700",
  meeting_booked: "bg-purple-100 text-purple-700",
  negotiating: "bg-amber-100 text-amber-700",
  won: "bg-green-100 text-green-800",
  lost: "bg-red-100 text-red-700",
};

export const DEAL_STAGES = [
  "cold",
  "contacted",
  "engaged",
  "meeting_booked",
  "negotiating",
  "won",
  "lost",
] as const;

/** Channel labels for display */
export const CHANNEL_LABELS: Record<string, string> = {
  email: "Email",
  linkedin_connect: "LinkedIn Connect",
  linkedin_message: "LinkedIn Message",
  linkedin_engage: "LinkedIn Engage",
  linkedin_insight: "LinkedIn Insight",
  linkedin_final: "LinkedIn Final",
};
