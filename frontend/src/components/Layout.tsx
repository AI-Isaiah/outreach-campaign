import { NavLink, Outlet } from "react-router-dom";
import GlobalSearchBar from "./GlobalSearchBar";

const links = [
  { to: "/", label: "Dashboard" },
  { to: "/queue", label: "Queue" },
  { to: "/campaigns", label: "Campaigns" },
  { to: "/contacts", label: "Contacts" },
  { to: "/templates", label: "Templates" },
  { to: "/insights", label: "Insights" },
  { to: "/settings", label: "Settings" },
];

export default function Layout() {
  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className="w-56 bg-gray-900 text-gray-300 flex flex-col shrink-0">
        <div className="px-5 py-5 border-b border-gray-700">
          <h1 className="text-white text-lg font-semibold tracking-tight">
            Outreach
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">Campaign Dashboard</p>
        </div>
        <div className="px-3 pt-3 pb-2">
          <GlobalSearchBar />
        </div>
        <nav className="flex-1 py-2 space-y-0.5 px-3">
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.to === "/"}
              className={({ isActive }) =>
                `block px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-gray-800 text-white"
                    : "hover:bg-gray-800/50 hover:text-white"
                }`
              }
            >
              {l.label}
            </NavLink>
          ))}
        </nav>
        <div className="px-5 py-4 border-t border-gray-700 text-xs text-gray-500">
          CLI + Web &middot; Shared DB
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
