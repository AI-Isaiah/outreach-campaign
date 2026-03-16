interface CryptoScoreBadgeProps {
  score: number | null;
  showLabel?: boolean;
}

export const scoreConfig = (score: number) => {
  if (score >= 80) return { bg: "bg-green-100", text: "text-green-700", ring: "ring-green-600/20" };
  if (score >= 60) return { bg: "bg-blue-100", text: "text-blue-700", ring: "ring-blue-600/20" };
  if (score >= 40) return { bg: "bg-yellow-100", text: "text-yellow-700", ring: "ring-yellow-600/20" };
  if (score >= 20) return { bg: "bg-gray-100", text: "text-gray-600", ring: "ring-gray-500/20" };
  return { bg: "bg-red-100", text: "text-red-700", ring: "ring-red-600/20" };
};

const categoryLabel = (score: number) => {
  if (score >= 80) return "Confirmed";
  if (score >= 60) return "Likely";
  if (score >= 40) return "Possible";
  if (score >= 20) return "No Signal";
  return "Unlikely";
};

export default function CryptoScoreBadge({ score, showLabel = false }: CryptoScoreBadgeProps) {
  if (score == null) {
    return (
      <span className="inline-flex items-center rounded-full bg-gray-50 px-2 py-0.5 text-xs font-medium text-gray-500 ring-1 ring-inset ring-gray-500/10">
        Pending
      </span>
    );
  }

  const config = scoreConfig(score);

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${config.bg} ${config.text} ${config.ring}`}
    >
      <span className="tabular-nums">{score}</span>
      {showLabel && <span className="font-medium">{categoryLabel(score)}</span>}
    </span>
  );
}
