import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";

export default function ContactList() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["contacts", page, query],
    queryFn: () => api.listContacts(page, query || undefined),
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setQuery(search);
    setPage(1);
  };

  const contacts = data?.contacts || [];
  const totalPages = data?.pages || 1;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Contacts</h1>
        <p className="text-gray-500 mt-1">
          {data?.total || 0} total contacts
        </p>
      </div>

      {/* Search */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          type="text"
          placeholder="Search by name, email, or company..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 px-4 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          type="submit"
          className="px-4 py-2 bg-gray-900 text-white rounded-md text-sm font-medium hover:bg-gray-800 transition-colors"
        >
          Search
        </button>
        {query && (
          <button
            type="button"
            onClick={() => {
              setSearch("");
              setQuery("");
              setPage(1);
            }}
            className="px-4 py-2 bg-gray-100 text-gray-700 rounded-md text-sm font-medium hover:bg-gray-200 transition-colors"
          >
            Clear
          </button>
        )}
      </form>

      {isLoading && <p className="text-gray-400">Loading...</p>}

      {contacts.length > 0 ? (
        <>
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                    Name
                  </th>
                  <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                    Company
                  </th>
                  <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                    Email
                  </th>
                  <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                    AUM ($M)
                  </th>
                  <th className="text-center px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                    Status
                  </th>
                  <th className="text-center px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                    GDPR
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {contacts.map((c: any) => (
                  <tr
                    key={c.id}
                    className="hover:bg-gray-50 transition-colors"
                  >
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
                    <td className="px-5 py-3 text-sm text-gray-600">
                      {c.company_name || "-"}
                    </td>
                    <td className="px-5 py-3 text-sm text-gray-500">
                      {c.email || "-"}
                    </td>
                    <td className="px-5 py-3 text-sm text-right text-gray-600">
                      {c.aum_millions
                        ? c.aum_millions.toLocaleString()
                        : "-"}
                    </td>
                    <td className="px-5 py-3 text-center">
                      <span
                        className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                          c.email_status === "valid"
                            ? "bg-green-100 text-green-800"
                            : c.email_status === "invalid"
                              ? "bg-red-100 text-red-700"
                              : "bg-gray-100 text-gray-600"
                        }`}
                      >
                        {c.email_status}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-center text-sm">
                      {c.is_gdpr ? (
                        <span className="text-red-500">Yes</span>
                      ) : (
                        <span className="text-gray-400">No</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between">
            <p className="text-sm text-gray-500">
              Page {page} of {totalPages}
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="px-3 py-1.5 bg-white border border-gray-200 rounded-md text-sm disabled:opacity-50 hover:bg-gray-50 transition-colors"
              >
                Previous
              </button>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="px-3 py-1.5 bg-white border border-gray-200 rounded-md text-sm disabled:opacity-50 hover:bg-gray-50 transition-colors"
              >
                Next
              </button>
            </div>
          </div>
        </>
      ) : (
        !isLoading && (
          <p className="text-gray-400 text-center py-12">
            No contacts found.
          </p>
        )
      )}
    </div>
  );
}
