export function SkeletonRow({ cols }: { cols: number }) {
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-5 py-4">
          <div className="h-4 bg-gray-200 rounded animate-pulse" />
        </td>
      ))}
    </tr>
  );
}

export function SkeletonCard() {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm space-y-3">
      <div className="h-3 w-24 bg-gray-200 rounded animate-pulse" />
      <div className="h-7 w-16 bg-gray-200 rounded animate-pulse" />
      <div className="h-3 w-32 bg-gray-200 rounded animate-pulse" />
    </div>
  );
}

export function SkeletonTable({ rows, cols }: { rows: number; cols: number }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-200">
            {Array.from({ length: cols }).map((_, i) => (
              <th key={i} className="px-5 py-3">
                <div className="h-3 w-20 bg-gray-200 rounded animate-pulse" />
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {Array.from({ length: rows }).map((_, i) => (
            <SkeletonRow key={i} cols={cols} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SkeletonMetricCard() {
  return (
    <div className="bg-white rounded-xl border-l-4 border-gray-200 p-4 shadow-sm">
      <div className="h-3 w-20 bg-gray-200 rounded animate-pulse" />
      <div className="h-7 w-12 bg-gray-200 rounded animate-pulse mt-2" />
    </div>
  );
}
