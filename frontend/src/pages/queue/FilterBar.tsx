export type ChannelFilter = "all" | "email" | "linkedin";

interface FilterBarProps {
  channelFilter: ChannelFilter;
  onChannelFilterChange: (f: ChannelFilter) => void;
  campaignFilter: string;
  onCampaignFilterChange: (v: string) => void;
  campaignNames: string[];
}

export default function FilterBar({
  channelFilter,
  onChannelFilterChange,
  campaignFilter,
  onCampaignFilterChange,
  campaignNames,
}: FilterBarProps) {
  return (
    <div className="flex gap-2 flex-wrap">
      {(["all", "email", "linkedin"] as ChannelFilter[]).map((f) => (
        <button
          key={f}
          className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
            channelFilter === f
              ? "bg-gray-900 text-white"
              : "bg-gray-100 text-gray-600 hover:bg-gray-200"
          }`}
          onClick={() => onChannelFilterChange(f)}
        >
          {f === "all" ? "All channels" : f === "email" ? "Email" : "LinkedIn"}
        </button>
      ))}

      {campaignNames.length > 0 && (
        <>
          <div className="w-px bg-gray-200 mx-1" />
          <select
            value={campaignFilter}
            onChange={(e) => onCampaignFilterChange(e.target.value)}
            className="px-3 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700 border-0 cursor-pointer hover:bg-gray-200 transition-colors appearance-none pr-6"
            style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")", backgroundRepeat: "no-repeat", backgroundPosition: "right 6px center" }}
          >
            <option value="">All campaigns ({campaignNames.length})</option>
            {campaignNames.map((cn) => (
              <option key={cn} value={cn}>{cn}</option>
            ))}
          </select>
        </>
      )}
    </div>
  );
}
