const statusColors: Record<string, string> = {
  queued: "bg-gray-100 text-gray-700",
  in_progress: "bg-blue-100 text-blue-700",
  replied_positive: "bg-green-100 text-green-800",
  replied_negative: "bg-red-100 text-red-700",
  no_response: "bg-yellow-100 text-yellow-800",
  bounced: "bg-red-100 text-red-700",
  active: "bg-green-100 text-green-800",
  completed: "bg-gray-100 text-gray-700",
  drafted: "bg-blue-100 text-blue-700",
  sent: "bg-green-100 text-green-800",
};

export default function StatusBadge({ status }: { status: string }) {
  const color = statusColors[status] || "bg-gray-100 text-gray-700";
  const label = status.replace(/_/g, " ");
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium capitalize ${color}`}
    >
      {label}
    </span>
  );
}
