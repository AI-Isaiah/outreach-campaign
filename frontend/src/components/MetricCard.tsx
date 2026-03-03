export default function MetricCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: "green" | "red" | "blue" | "yellow";
}) {
  const accentColors = {
    green: "border-green-400",
    red: "border-red-400",
    blue: "border-blue-400",
    yellow: "border-yellow-400",
  };
  const border = accent ? accentColors[accent] : "border-gray-200";

  return (
    <div className={`bg-white rounded-lg border-l-4 ${border} p-4 shadow-sm`}>
      <p className="text-sm text-gray-500 font-medium">{label}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}
