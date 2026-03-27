import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Users, Search as SearchIcon, Upload, Plus } from "lucide-react";
import { api } from "../api/client";
import type { ContactListResponse, Contact, Product } from "../types";
import LifecycleBadge from "../components/LifecycleBadge";
import StatusBadge from "../components/StatusBadge";
import CreateContactModal from "../components/CreateContactModal";
import Pagination from "../components/Pagination";
import { useToast } from "../components/Toast";
import { SkeletonTable } from "../components/Skeleton";
import EmptyState from "../components/EmptyState";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";
import Input from "../components/ui/Input";
import Select from "../components/ui/Select";
import { LIFECYCLE_STAGES } from "../constants";
import { queryKeys } from "../api/queryKeys";

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "queued", label: "Queued" },
  { value: "in_progress", label: "In Progress" },
  { value: "replied_positive", label: "Replied (Positive)" },
  { value: "replied_negative", label: "Replied (Negative)" },
  { value: "no_response", label: "No Response" },
  { value: "completed", label: "Completed" },
  { value: "unsubscribed", label: "Unsubscribed" },
  { value: "bounced", label: "Bounced" },
];

const FIRM_TYPES = [
  { value: "", label: "All firm types" },
  { value: "Fund of Funds", label: "Fund of Funds" },
  { value: "Family Office", label: "Family Office" },
  { value: "Wealth Manager", label: "Wealth Manager" },
  { value: "Pension Fund", label: "Pension Fund" },
  { value: "Endowment", label: "Endowment" },
  { value: "Insurance", label: "Insurance" },
  { value: "Sovereign Wealth", label: "Sovereign Wealth" },
  { value: "Bank", label: "Bank" },
  { value: "Consultant", label: "Consultant" },
];

const _stageLabel = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const LIFECYCLE_OPTIONS = [
  { value: "", label: "All stages" },
  ...LIFECYCLE_STAGES.map((s) => ({ value: s, label: _stageLabel(s) })),
];

const BULK_LIFECYCLE_OPTIONS = LIFECYCLE_STAGES.map((s) => ({ value: s, label: _stageLabel(s) }));

export default function ContactList() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [sortBy, setSortBy] = useState<string | undefined>();
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [filters, setFilters] = useState({
    search: "",
    status: "",
    company_type: "",
    min_aum: "",
    max_aum: "",
    lifecycle_stage: "",
    newsletter_subscriber: "" as "" | "true" | "false",
    product_id: "",
  });

  const queryClient = useQueryClient();
  const { toast } = useToast();

  const { data: products } = useQuery<Product[]>({
    queryKey: queryKeys.products.all,
    queryFn: () => api.listProducts(),
  });

  const { data, isLoading, isError, error, refetch } = useQuery<ContactListResponse>({
    queryKey: queryKeys.contacts.all(page, filters, sortBy, sortDir),
    queryFn: () =>
      api.listCrmContacts({
        search: filters.search || undefined,
        status: filters.status || undefined,
        company_type: filters.company_type || undefined,
        min_aum: filters.min_aum ? Number(filters.min_aum) : undefined,
        max_aum: filters.max_aum ? Number(filters.max_aum) : undefined,
        lifecycle_stage: filters.lifecycle_stage || undefined,
        newsletter_subscriber: filters.newsletter_subscriber ? filters.newsletter_subscriber === "true" : undefined,
        product_id: filters.product_id ? Number(filters.product_id) : undefined,
        page,
        sort_by: sortBy,
        sort_dir: sortDir,
      }),
  });

  const bulkLifecycleMutation = useMutation({
    mutationFn: ({ ids, stage }: { ids: number[]; stage: string }) =>
      api.bulkUpdateLifecycle(ids, stage),
    onSuccess: (result) => {
      toast(`Updated ${result.updated} contacts`, "success");
      setSelectedIds(new Set());
      queryClient.invalidateQueries({ queryKey: ["crm-contacts"] });
    },
    onError: (err: Error) => {
      toast(err.message, "error");
    },
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setFilters((f) => ({ ...f, search }));
    setPage(1);
  };

  const clearFilters = () => {
    setSearch("");
    setFilters({ search: "", status: "", company_type: "", min_aum: "", max_aum: "", lifecycle_stage: "", newsletter_subscriber: "", product_id: "" });
    setPage(1);
  };

  const handleSort = (key: string) => {
    if (sortBy === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(key);
      setSortDir("asc");
    }
    setPage(1);
  };

  const hasFilters = filters.search || filters.status || filters.company_type || filters.min_aum || filters.max_aum || filters.lifecycle_stage || filters.newsletter_subscriber || filters.product_id;

  const contacts = data?.contacts || [];
  const totalPages = data?.pages || 1;

  const allSelected = contacts.length > 0 && contacts.every((c) => selectedIds.has(c.id));

  const toggleAll = () => {
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(contacts.map((c) => c.id)));
    }
  };

  const toggleOne = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleBulkLifecycle = (stage: string) => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    bulkLifecycleMutation.mutate({ ids, stage });
  };

  const sortIndicator = (key: string) => {
    if (sortBy !== key) return null;
    return <span className="text-gray-400 ml-1">{sortDir === "asc" ? "\u25B2" : "\u25BC"}</span>;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Contacts</h1>
          <p className="text-sm text-gray-500 mt-1">
            {data?.total || 0} total contacts
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/import">
            <Button variant="secondary" size="md" leftIcon={<Upload size={16} />}>
              Import CSV
            </Button>
          </Link>
          <Button
            variant="primary"
            size="md"
            leftIcon={<Plus size={16} />}
            onClick={() => setShowCreateModal(true)}
          >
            Add Contact
          </Button>
        </div>
      </div>

      {/* Search */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="flex-1">
          <Input
            placeholder="Search by name, email, or company..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            leftIcon={<SearchIcon size={16} />}
          />
        </div>
        <Button variant="primary" size="md" type="submit">
          Search
        </Button>
        {hasFilters && (
          <Button variant="ghost" size="md" type="button" onClick={clearFilters}>
            Clear all
          </Button>
        )}
      </form>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <Select
          value={filters.status}
          onChange={(e) => { setFilters((f) => ({ ...f, status: e.target.value })); setPage(1); }}
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </Select>

        <Select
          value={filters.company_type}
          onChange={(e) => { setFilters((f) => ({ ...f, company_type: e.target.value })); setPage(1); }}
        >
          {FIRM_TYPES.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </Select>

        <Select
          value={filters.lifecycle_stage}
          onChange={(e) => { setFilters((f) => ({ ...f, lifecycle_stage: e.target.value })); setPage(1); }}
        >
          {LIFECYCLE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </Select>

        <Select
          value={filters.newsletter_subscriber}
          onChange={(e) => { setFilters((f) => ({ ...f, newsletter_subscriber: e.target.value as "" | "true" | "false" })); setPage(1); }}
        >
          <option value="">Newsletter: All</option>
          <option value="true">Subscribed</option>
          <option value="false">Not subscribed</option>
        </Select>

        <Select
          value={filters.product_id}
          onChange={(e) => { setFilters((f) => ({ ...f, product_id: e.target.value })); setPage(1); }}
        >
          <option value="">All products</option>
          {(products || []).map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </Select>

        <div className="flex items-center gap-1">
          <input
            type="number"
            placeholder="Min AUM ($M)"
            value={filters.min_aum}
            onChange={(e) => { setFilters((f) => ({ ...f, min_aum: e.target.value })); setPage(1); }}
            className="w-32 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <span className="text-gray-400 text-sm">-</span>
          <input
            type="number"
            placeholder="Max AUM ($M)"
            value={filters.max_aum}
            onChange={(e) => { setFilters((f) => ({ ...f, max_aum: e.target.value })); setPage(1); }}
            className="w-32 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      {/* Loading */}
      {isLoading && <SkeletonTable rows={8} cols={8} />}

      {/* Error */}
      {isError && (
        <ErrorCard
          message={(error as Error).message}
          onRetry={() => refetch()}
        />
      )}

      {/* Table */}
      {!isLoading && contacts.length > 0 ? (
        <>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="w-10 px-3 py-3">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      className="rounded border-gray-300"
                    />
                  </th>
                  <th
                    className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide cursor-pointer select-none hover:text-gray-700"
                    onClick={() => handleSort("name")}
                  >
                    Name{sortIndicator("name")}
                  </th>
                  <th
                    className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide cursor-pointer select-none hover:text-gray-700"
                    onClick={() => handleSort("company")}
                  >
                    Company{sortIndicator("company")}
                  </th>
                  <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Email
                  </th>
                  <th
                    className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide cursor-pointer select-none hover:text-gray-700"
                    onClick={() => handleSort("aum")}
                  >
                    AUM ($M){sortIndicator("aum")}
                  </th>
                  <th className="text-center px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Lifecycle
                  </th>
                  <th className="text-center px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Status
                  </th>
                  <th className="text-center px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    GDPR
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {contacts.map((c: Contact) => (
                  <tr
                    key={c.id}
                    className={`hover:bg-gray-50 transition-colors ${selectedIds.has(c.id) ? "bg-blue-50" : ""}`}
                  >
                    <td className="w-10 px-3 py-3">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(c.id)}
                        onChange={() => toggleOne(c.id)}
                        className="rounded border-gray-300"
                      />
                    </td>
                    <td className="px-5 py-3">
                      <Link
                        to={`/contacts/${c.id}`}
                        className="font-medium text-blue-600 hover:text-blue-800"
                      >
                        {c.full_name ||
                          `${c.first_name || ""} ${c.last_name || ""}`.trim() ||
                          "-"}
                      </Link>
                    </td>
                    <td className="px-5 py-3 text-sm text-gray-600 max-w-[200px] truncate" title={c.company_name || ""}>
                      {c.company_name || "-"}
                    </td>
                    <td className="px-5 py-3 text-sm text-gray-500 max-w-[220px] truncate" title={c.email || ""}>
                      {c.email || "-"}
                    </td>
                    <td className="px-5 py-3 text-sm text-right text-gray-600">
                      {c.aum_millions
                        ? c.aum_millions.toLocaleString()
                        : "-"}
                    </td>
                    <td className="px-5 py-3 text-center">
                      <LifecycleBadge stage={c.lifecycle_stage || "cold"} />
                    </td>
                    <td className="px-5 py-3 text-center">
                      <StatusBadge status={c.email_status} />
                    </td>
                    <td className="px-5 py-3 text-center">
                      {c.is_gdpr ? (
                        <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800">
                          GDPR
                        </span>
                      ) : (
                        <span className="text-xs text-gray-400">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
        </>
      ) : (
        !isLoading && !isError && (
          <EmptyState
            icon={<Users size={40} />}
            title="No contacts found"
            description={
              hasFilters
                ? "Try adjusting your search or filters."
                : "Import contacts or add them manually to get started."
            }
            action={
              hasFilters
                ? { label: "Clear Filters", onClick: clearFilters }
                : undefined
            }
          />
        )
      )}

      {/* Floating bulk action bar */}
      {selectedIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 bg-gray-900 text-white rounded-xl shadow-xl px-5 py-3 flex items-center gap-4 animate-page-in">
          <span className="text-sm font-medium">
            {selectedIds.size} selected
          </span>
          <div className="w-px h-5 bg-gray-700" />
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-400">Update Lifecycle:</label>
            <select
              onChange={(e) => {
                if (e.target.value) handleBulkLifecycle(e.target.value);
                e.target.value = "";
              }}
              className="px-2 py-1 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200"
              defaultValue=""
            >
              <option value="" disabled>Choose...</option>
              {BULK_LIFECYCLE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <button
            onClick={() => toast("Export CSV coming soon", "info")}
            className="px-3 py-1 bg-gray-800 border border-gray-700 rounded-lg text-sm hover:bg-gray-700 transition-colors"
          >
            Export CSV
          </button>
          <button
            onClick={() => toast("Add Tag coming soon", "info")}
            className="px-3 py-1 bg-gray-800 border border-gray-700 rounded-lg text-sm hover:bg-gray-700 transition-colors"
          >
            Add Tag
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="text-gray-400 hover:text-white text-sm ml-2"
          >
            Clear
          </button>
        </div>
      )}

      <CreateContactModal open={showCreateModal} onClose={() => setShowCreateModal(false)} />
    </div>
  );
}
