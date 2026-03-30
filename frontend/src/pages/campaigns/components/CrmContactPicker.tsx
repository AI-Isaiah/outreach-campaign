import { useState, useEffect, useMemo, useRef } from "react";
import { useDebouncedValue } from "../../../hooks/useDebouncedValue";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Search, Loader2, ChevronLeft, ChevronRight, ChevronDown, X } from "lucide-react";
import Input from "../../../components/ui/Input";
import { contactsApi } from "../../../api/contacts";
import { campaignsApi } from "../../../api/campaigns";

type SortCol = "name" | "company" | "aum";
type SortDir = "asc" | "desc";

export default function CrmContactPicker({
  selectedIds,
  onSelectionChange,
}: {
  selectedIds: Set<number>;
  onSelectionChange: (ids: Set<number>) => void;
}) {
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(50);
  const [sortBy, setSortBy] = useState<SortCol>("aum");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [hasLinkedin, setHasLinkedin] = useState(false);
  const [hasEmail, setHasEmail] = useState(false);
  const [onePerCompany, setOnePerCompany] = useState(false);
  const [excludeCampaigns, setExcludeCampaigns] = useState<number[]>([]);
  const [neverContacted, setNeverContacted] = useState(false);
  const [campaignDropdownOpen, setCampaignDropdownOpen] = useState(false);
  const campaignDropdownRef = useRef<HTMLDivElement>(null);

  // Close campaign dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (campaignDropdownRef.current && !campaignDropdownRef.current.contains(e.target as Node)) {
        setCampaignDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Fetch campaigns for the exclusion dropdown
  const { data: campaignsList } = useQuery({
    queryKey: ["campaigns-list-for-filter"],
    queryFn: () => campaignsApi.listCampaigns(),
  });

  // Reset page when search changes
  useEffect(() => { setPage(1); }, [debouncedSearch]);

  const { data, isLoading } = useQuery({
    queryKey: ["contacts", "picker", debouncedSearch, page, perPage, sortBy, sortDir, hasLinkedin, hasEmail, excludeCampaigns, neverContacted],
    queryFn: () =>
      contactsApi.listContacts(page, debouncedSearch || undefined, {
        per_page: perPage,
        sort_by: sortBy,
        sort_dir: sortDir,
        has_linkedin: hasLinkedin || undefined,
        has_email: hasEmail || undefined,
        exclude_campaigns: excludeCampaigns.length > 0 ? excludeCampaigns.join(",") : undefined,
        never_contacted: neverContacted || undefined,
      }),
    placeholderData: keepPreviousData,
  });

  const crmContacts = data?.contacts ?? [];
  const totalPages = data?.pages ?? 1;
  const total = data?.total ?? 0;

  const toggleSort = (col: SortCol) => {
    if (sortBy === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortDir(col === "name" || col === "company" ? "asc" : "desc");
    }
    setPage(1);
  };

  const sortArrow = (col: SortCol) =>
    sortBy === col ? (sortDir === "asc" ? " \u25B2" : " \u25BC") : "";

  // Pre-compute selected companies to avoid O(n^2) scan per row
  const selectedCompanies = useMemo(() => {
    if (!onePerCompany) return new Set<string>();
    const s = new Set<string>();
    for (const c of crmContacts) {
      if (selectedIds.has(c.id) && c.company_name) s.add(c.company_name);
    }
    return s;
  }, [crmContacts, selectedIds, onePerCompany]);

  const toggleOne = (id: number) => {
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      // Enforce one-per-company: block if another contact from same company is already selected
      if (onePerCompany) {
        const contact = crmContacts.find((c) => c.id === id);
        if (contact?.company_name && selectedCompanies.has(contact.company_name)) return;
      }
      next.add(id);
    }
    onSelectionChange(next);
  };

  // When onePerCompany is on, "select all" picks only the top-AUM contact per company
  const selectableOnPage = onePerCompany
    ? (() => {
        const seen = new Set<string>();
        // crmContacts already sorted by AUM desc from API, so first per company is highest
        return crmContacts.filter((c) => {
          const key = c.company_name || `__no_company_${c.id}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
      })()
    : crmContacts;

  const allOnPageSelected =
    selectableOnPage.length > 0 && selectableOnPage.every((c) => selectedIds.has(c.id));

  const togglePage = () => {
    const next = new Set(selectedIds);
    if (allOnPageSelected) {
      crmContacts.forEach((c) => next.delete(c.id));
    } else {
      selectableOnPage.forEach((c) => next.add(c.id));
    }
    onSelectionChange(next);
  };

  const formatAum = (aum: number | null | undefined) => {
    if (aum == null) return "-";
    if (aum >= 1000) return `$${(aum / 1000).toFixed(1)}B`;
    return `$${aum}M`;
  };

  return (
    <div className="space-y-3">
      <Input
        placeholder="Search by name, email, or company..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        leftIcon={<Search size={16} />}
      />

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-gray-500 mr-1">Filter:</span>
        {[
          { label: "Has LinkedIn", active: hasLinkedin, toggle: () => { setHasLinkedin(!hasLinkedin); setPage(1); } },
          { label: "Has Email", active: hasEmail, toggle: () => { setHasEmail(!hasEmail); setPage(1); } },
          { label: "Never contacted", active: neverContacted, toggle: () => { setNeverContacted(!neverContacted); setPage(1); } },
          { label: "One per company", active: onePerCompany, toggle: () => {
            const next = !onePerCompany;
            setOnePerCompany(next);
            setPage(1);
            // Prune duplicate-company selections when enabling the filter
            if (next && crmContacts.length > 0) {
              const seen = new Set<string>();
              const pruned = new Set<number>();
              for (const c of crmContacts) {
                if (!selectedIds.has(c.id)) continue;
                const key = c.company_name || `__no_company_${c.id}`;
                if (seen.has(key)) continue;
                seen.add(key);
                pruned.add(c.id);
              }
              if (pruned.size < selectedIds.size) onSelectionChange(pruned);
            }
          } },
        ].map((f) => (
          <button
            key={f.label}
            onClick={f.toggle}
            className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
              f.active
                ? "bg-gray-900 text-white border-gray-900"
                : "bg-white text-gray-600 border-gray-200 hover:border-gray-400"
            }`}
          >
            {f.active && "\u2713 "}{f.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-400">
          Show:
          {[50, 100].map((n) => (
            <button
              key={n}
              onClick={() => { setPerPage(n); setPage(1); }}
              className={`ml-1.5 ${perPage === n ? "text-gray-900 font-medium" : "text-gray-400 hover:text-gray-600"}`}
            >
              {n}
            </button>
          ))}
        </span>
      </div>

      {/* Exclude campaigns dropdown */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative" ref={campaignDropdownRef}>
          <button
            onClick={() => setCampaignDropdownOpen((o) => !o)}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
              excludeCampaigns.length > 0
                ? "bg-gray-900 text-white border-gray-900"
                : "bg-white text-gray-600 border-gray-200 hover:border-gray-400"
            }`}
          >
            Exclude campaigns{excludeCampaigns.length > 0 && ` (${excludeCampaigns.length})`}
            <ChevronDown size={12} />
          </button>
          {campaignDropdownOpen && (
            <div className="absolute z-20 mt-1 left-0 bg-white border border-gray-200 rounded-lg shadow-lg py-1 w-64 max-h-48 overflow-y-auto">
              {(campaignsList ?? []).length === 0 ? (
                <div className="px-3 py-2 text-xs text-gray-400">No campaigns</div>
              ) : (
                (campaignsList ?? []).map((camp) => (
                  <label
                    key={camp.id}
                    className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={excludeCampaigns.includes(camp.id)}
                      onChange={() => {
                        setExcludeCampaigns((prev) =>
                          prev.includes(camp.id) ? prev.filter((id) => id !== camp.id) : [...prev, camp.id],
                        );
                        setPage(1);
                      }}
                      className="rounded border-gray-300"
                    />
                    <span className="text-xs text-gray-700 truncate">{camp.name}</span>
                  </label>
                ))
              )}
            </div>
          )}
        </div>
        {excludeCampaigns.length > 0 &&
          excludeCampaigns.map((cid) => {
            const camp = (campaignsList ?? []).find((c) => c.id === cid);
            return (
              <span
                key={cid}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 text-xs text-gray-600"
              >
                {camp?.name ?? `#${cid}`}
                <button
                  onClick={() => { setExcludeCampaigns((prev) => prev.filter((id) => id !== cid)); setPage(1); }}
                  className="text-gray-400 hover:text-gray-600"
                  aria-label={`Remove ${camp?.name ?? cid}`}
                >
                  <X size={10} />
                </button>
              </span>
            );
          })}
      </div>

      {isLoading && crmContacts.length === 0 ? (
        <div className="flex items-center justify-center py-12 text-gray-400">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : crmContacts.length === 0 ? (
        <div className="text-center py-8 text-sm text-gray-500">
          {debouncedSearch
            ? `No contacts matching "${debouncedSearch}"`
            : "No contacts in your CRM yet"}
        </div>
      ) : (
        <>
          <div className="border border-gray-200 rounded-lg overflow-hidden max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="w-10 px-3 py-2">
                    <input
                      type="checkbox"
                      checked={allOnPageSelected}
                      onChange={togglePage}
                      className="rounded border-gray-300"
                      aria-label="Select all on this page"
                    />
                  </th>
                  <th
                    onClick={() => toggleSort("name")}
                    className="text-left px-3 py-2 text-xs font-medium text-gray-500 uppercase tracking-wide cursor-pointer select-none hover:text-gray-700"
                  >
                    Name{sortArrow("name")}
                  </th>
                  <th
                    onClick={() => toggleSort("company")}
                    className="text-left px-3 py-2 text-xs font-medium text-gray-500 uppercase tracking-wide cursor-pointer select-none hover:text-gray-700"
                  >
                    Company{sortArrow("company")}
                  </th>
                  <th
                    onClick={() => toggleSort("aum")}
                    className="text-right px-3 py-2 text-xs font-medium text-gray-500 uppercase tracking-wide cursor-pointer select-none hover:text-gray-700"
                  >
                    AUM{sortArrow("aum")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {crmContacts.map((c) => {
                  const checked = selectedIds.has(c.id);
                  const companyConflict = !checked && onePerCompany && !!c.company_name && selectedCompanies.has(c.company_name);
                  return (
                    <tr
                      key={c.id}
                      className={`hover:bg-gray-50 cursor-pointer transition-colors ${
                        checked ? "bg-blue-50" : companyConflict ? "opacity-40" : ""
                      }`}
                      onClick={() => toggleOne(c.id)}
                      title={companyConflict ? `Another contact at ${c.company_name} is already selected` : undefined}
                    >
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleOne(c.id)}
                          className="rounded border-gray-300"
                          aria-label={`Select ${c.full_name || c.first_name}`}
                        />
                      </td>
                      <td className="px-3 py-2 font-medium">
                        {c.full_name || [c.first_name, c.last_name].filter(Boolean).join(" ")}
                      </td>
                      <td className="px-3 py-2 text-gray-500">{c.company_name || "-"}</td>
                      <td className="px-3 py-2 text-right text-gray-500">{formatAum(c.aum_millions)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Footer: selection count + pagination */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-500">
              {selectedIds.size} selected
              {total > 0 && ` of ${total}`}
              {selectedIds.size > 0 && (
                <button
                  onClick={() => onSelectionChange(new Set())}
                  className="ml-2 text-xs text-blue-600 hover:text-blue-800 hover:underline"
                >
                  Clear all
                </button>
              )}
            </span>
            {totalPages > 1 && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-2 py-1 text-xs font-medium text-gray-600 border border-gray-200 rounded hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <ChevronLeft size={14} />
                </button>
                <span className="text-xs text-gray-500">
                  Page {page} of {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="px-2 py-1 text-xs font-medium text-gray-600 border border-gray-200 rounded hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
