interface PaginationProps {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  totalItems?: number;
  pageSize?: number;
  onPageSizeChange?: (size: number) => void;
  pageSizeOptions?: number[];
}

const DEFAULT_PAGE_SIZES = [50, 100, 200, 500];

export default function Pagination({
  page,
  totalPages,
  onPageChange,
  totalItems,
  pageSize,
  onPageSizeChange,
  pageSizeOptions = DEFAULT_PAGE_SIZES,
}: PaginationProps) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-4">
        <p className="text-sm text-gray-500">
          Page {page} of {totalPages}
          {totalItems !== undefined && (
            <span className="text-gray-400 ml-1">({totalItems} rows)</span>
          )}
        </p>
        {onPageSizeChange && (
          <select
            value={pageSize === Infinity || !pageSize ? "all" : pageSize}
            onChange={(e) => {
              const val = e.target.value;
              onPageSizeChange(val === "all" ? Infinity : Number(val));
            }}
            className="text-sm border border-gray-200 rounded-md px-2 py-1 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1"
          >
            {pageSizeOptions.map((size) => (
              <option key={size} value={size}>
                {size} rows
              </option>
            ))}
            <option value="all">All rows</option>
          </select>
        )}
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page <= 1}
          className="px-3 py-1.5 bg-white border border-gray-200 rounded-md text-sm disabled:opacity-50 hover:bg-gray-50 transition-colors"
        >
          Previous
        </button>
        <button
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages}
          className="px-3 py-1.5 bg-white border border-gray-200 rounded-md text-sm disabled:opacity-50 hover:bg-gray-50 transition-colors"
        >
          Next
        </button>
      </div>
    </div>
  );
}
