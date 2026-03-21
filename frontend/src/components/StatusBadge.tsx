import React from "react";
import { STATUS_COLORS } from "../constants";

function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLORS[status] || "bg-gray-100 text-gray-700";
  const label = status.replace(/_/g, " ");
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium capitalize ${color}`}
    >
      {label}
    </span>
  );
}

export default React.memo(StatusBadge);
