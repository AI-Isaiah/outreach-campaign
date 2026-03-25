import React from "react";

const stageColors: Record<string, string> = {
  discussed: "bg-gray-100 text-gray-700",
  interested: "bg-blue-100 text-blue-700",
  due_diligence: "bg-amber-100 text-amber-700",
  invested: "bg-green-100 text-green-800",
  declined: "bg-red-100 text-red-700",
};

function ProductStageBadge({ stage }: { stage: string }) {
  const color = stageColors[stage] || "bg-gray-100 text-gray-700";
  const label = stage.replace(/_/g, " ");
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium capitalize ${color}`}
    >
      {label}
    </span>
  );
}

export default React.memo(ProductStageBadge);
