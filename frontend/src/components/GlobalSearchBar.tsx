import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { SearchResults } from "../types";

export default function GlobalSearchBar() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const navigate = useNavigate();
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const abortControllerRef = useRef<AbortController>();

  // Cmd+K / Ctrl+K keyboard shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    if (query.length < 2) {
      setResults(null);
      setIsOpen(false);
      return;
    }

    clearTimeout(timerRef.current);
    abortControllerRef.current?.abort();
    abortControllerRef.current = new AbortController();

    timerRef.current = setTimeout(async () => {
      try {
        const data = await api.globalSearch(query);
        setResults(data);
        setIsOpen(true);
      } catch {
        setResults(null);
      }
    }, 300);

    return () => {
      clearTimeout(timerRef.current);
      abortControllerRef.current?.abort();
    };
  }, [query]);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const handleSelect = (type: string, id: number) => {
    setIsOpen(false);
    setQuery("");
    if (type === "contact") navigate(`/contacts/${id}`);
    else if (type === "company") navigate(`/companies/${id}`);
    else if (type === "note") navigate(`/contacts/${id}`);
  };

  return (
    <div ref={ref} className="relative">
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          placeholder="Search..."
          aria-label="Search campaigns, contacts, and companies"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full px-3 py-1.5 pr-12 bg-gray-800 border border-gray-700 rounded-md text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <kbd className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none text-[10px] text-gray-500 bg-gray-700 px-1.5 py-0.5 rounded">
          {"\u2318"}K
        </kbd>
      </div>

      {isOpen && results && results.total > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-white rounded-lg shadow-lg border border-gray-200 z-50 max-h-80 overflow-y-auto">
          {results.contacts.length > 0 && (
            <div>
              <div className="px-3 py-1.5 text-xs font-semibold text-gray-500 bg-gray-50">
                Contacts
              </div>
              {results.contacts.map((c) => (
                <button
                  key={`c-${c.id}`}
                  onClick={() => handleSelect("contact", c.id)}
                  className="w-full text-left px-3 py-2 hover:bg-gray-50 text-sm"
                >
                  <span className="font-medium text-gray-900">
                    {c.full_name}
                  </span>
                  {c.company_name && (
                    <span className="text-gray-400 ml-2">{c.company_name}</span>
                  )}
                </button>
              ))}
            </div>
          )}

          {results.companies.length > 0 && (
            <div>
              <div className="px-3 py-1.5 text-xs font-semibold text-gray-500 bg-gray-50">
                Companies
              </div>
              {results.companies.map((co) => (
                <button
                  key={`co-${co.id}`}
                  onClick={() => handleSelect("company", co.id)}
                  className="w-full text-left px-3 py-2 hover:bg-gray-50 text-sm"
                >
                  <span className="font-medium text-gray-900">{co.name}</span>
                  {co.firm_type && (
                    <span className="text-gray-400 ml-2">{co.firm_type}</span>
                  )}
                </button>
              ))}
            </div>
          )}

          {results.messages.length > 0 && (
            <div>
              <div className="px-3 py-1.5 text-xs font-semibold text-gray-500 bg-gray-50">
                Messages
              </div>
              {results.messages.map((m) => (
                <button
                  key={`m-${m.id}`}
                  onClick={() => handleSelect("note", m.contact_id)}
                  className="w-full text-left px-3 py-2 hover:bg-gray-50 text-sm"
                >
                  <span className="font-medium text-gray-900">
                    {m.contact_name}
                  </span>
                  <span className="text-gray-400 ml-2 truncate">
                    {m.content.slice(0, 60)}...
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
