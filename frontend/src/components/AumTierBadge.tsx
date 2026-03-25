const TIER_COLORS: Record<string, string> = {
  "$0-100M": "bg-gray-100 text-gray-600",
  "$100M-500M": "bg-blue-100 text-blue-700",
  "$500M-1B": "bg-purple-100 text-purple-700",
  "$1B+": "bg-amber-100 text-amber-700",
};

export default function AumTierBadge({ tier }: { tier: string }) {
  const colors = TIER_COLORS[tier] || "bg-gray-100 text-gray-600";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${colors}`}>
      {tier}
    </span>
  );
}
