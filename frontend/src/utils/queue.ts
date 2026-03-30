export const REMOVE_REASON = "Remove from Contacts";

export const SKIP_REASONS = [
  "Not relevant now",
  "Bad timing",
  "Need more research",
  "Too junior",
  "Other",
  REMOVE_REASON,
];

export function splitName(fullName: string): [string, string] {
  const parts = fullName.trim().split(/\s+/);
  if (parts.length <= 1) return [parts[0] || "", ""];
  return [parts[0], parts.slice(1).join(" ")];
}
