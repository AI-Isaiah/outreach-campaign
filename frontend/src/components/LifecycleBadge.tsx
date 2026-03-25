import React from "react";
import { LIFECYCLE_COLORS } from "../constants";

function LifecycleBadge({ stage }: { stage: string }) {
  const color = LIFECYCLE_COLORS[stage] || "bg-gray-100 text-gray-700";
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium capitalize ${color}`}
    >
      {stage}
    </span>
  );
}

export default React.memo(LifecycleBadge);
