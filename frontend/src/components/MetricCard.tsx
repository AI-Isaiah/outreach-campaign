import React from "react";

function MetricCard({
  label,
  value,
  sub,
  accent,
  trend,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: "green" | "red" | "blue" | "yellow";
  trend?: number;
}) {
  const accentColors = {
    green: "border-green-400",
    red: "border-red-400",
    blue: "border-blue-400",
    yellow: "border-yellow-400",
  };
  const border = accent ? accentColors[accent] : "border-gray-200";

  return (
    <div className={`bg-white rounded-xl border-l-4 ${border} p-4 shadow-sm`}>
      <p className="text-sm text-gray-500 font-medium">{label}</p>
      <div className="flex items-baseline gap-2 mt-1">
        <p className="text-2xl font-bold">{value}</p>
        {trend != null && trend !== 0 && (
          <span
            className={`inline-flex items-center text-xs font-medium ${
              trend > 0 ? "text-green-600" : "text-red-600"
            }`}
          >
            <svg
              className={`w-3 h-3 mr-0.5 ${trend < 0 ? "rotate-180" : ""}`}
              viewBox="0 0 12 12"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path d="M6 2L10 8H2L6 2Z" fill="currentColor" />
            </svg>
            {Math.abs(trend).toFixed(1)}%
          </span>
        )}
      </div>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

export default React.memo(MetricCard);
