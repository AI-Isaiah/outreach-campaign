export const SKIP_REASONS = [
  "Not relevant now",
  "Bad timing",
  "Need more research",
  "Too junior",
  "Other",
  "Delete from Database",
];

export function splitName(fullName: string): [string, string] {
  const parts = fullName.trim().split(/\s+/);
  if (parts.length <= 1) return [parts[0] || "", ""];
  return [parts[0], parts.slice(1).join(" ")];
}
