export default function HealthScoreBadge({ score, totalSent }: { score?: number | null; totalSent?: number }) {
  if (score == null || (score === 0 && (totalSent === 0 || totalSent == null))) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-gray-100 text-gray-500">
        N/A
      </span>
    );
  }
  const color =
    score >= 70
      ? "bg-green-100 text-green-800"
      : score >= 40
        ? "bg-amber-100 text-amber-800"
        : "bg-red-100 text-red-800";
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${color}`}>
      {score}
    </span>
  );
}
