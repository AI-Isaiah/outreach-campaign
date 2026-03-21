import { useState, useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  ListTodo,
  Kanban,
  Mail,
  Megaphone,
  Users,
  Newspaper,
  FileText,
  BarChart3,
  Search,
  Settings,
  Menu,
  X,
  LogOut,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import GlobalSearchBar from "./GlobalSearchBar";

const links = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/queue", label: "Queue", icon: ListTodo },
  { to: "/pipeline", label: "Pipeline", icon: Kanban },
  { to: "/inbox", label: "Inbox", icon: Mail },
  { to: "/campaigns", label: "Campaigns", icon: Megaphone },
  { to: "/contacts", label: "Contacts", icon: Users },
  { to: "/newsletters", label: "Newsletters", icon: Newspaper },
  { to: "/templates", label: "Templates", icon: FileText },
  { to: "/research", label: "Research", icon: Search },
  { to: "/insights", label: "Insights", icon: BarChart3 },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();
  const { user, logout } = useAuth();

  // Close sidebar on navigation
  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  const sidebarContent = (
    <>
      <div className="px-5 py-5 border-b border-gray-700">
        <h1 className="text-white text-lg font-semibold tracking-tight">
          Outreach
        </h1>
        <p className="text-xs text-gray-500 mt-0.5">Campaign Dashboard</p>
      </div>
      <div className="px-3 pt-3 pb-2">
        <GlobalSearchBar />
      </div>
      <nav className="flex-1 py-2 space-y-0.5 px-3" aria-label="Main navigation">
        {links.map((l) => {
          const Icon = l.icon;
          return (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-gray-800 text-white"
                    : "hover:bg-gray-800/50 hover:text-white"
                }`
              }
            >
              <Icon size={18} className="shrink-0" />
              {l.label}
            </NavLink>
          );
        })}
      </nav>
      <div className="px-4 py-4 border-t border-gray-700 flex items-center gap-3">
        <div className="w-7 h-7 rounded-full bg-gray-700 flex items-center justify-center text-xs font-medium text-gray-300 shrink-0">
          {user?.name?.charAt(0)?.toUpperCase() || user?.email?.charAt(0)?.toUpperCase() || "?"}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-gray-300 truncate">{user?.name || "User"}</p>
          <p className="text-xs text-gray-500 truncate">{user?.email}</p>
        </div>
        <button
          onClick={logout}
          className="text-gray-500 hover:text-gray-300 shrink-0"
          aria-label="Sign out"
        >
          <LogOut size={16} />
        </button>
      </div>
    </>
  );

  return (
    <div className="min-h-screen flex">
      {/* Mobile top bar */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-40 bg-gray-900 px-4 py-3 flex items-center justify-between">
        <button
          onClick={() => setSidebarOpen(true)}
          className="text-gray-300 hover:text-white"
          aria-label="Open menu"
        >
          <Menu size={24} />
        </button>
        <h1 className="text-white text-base font-semibold">Outreach</h1>
        <div className="w-6" /> {/* spacer for centering */}
      </div>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/20"
            onClick={() => setSidebarOpen(false)}
          />
          {/* Sidebar */}
          <aside className="relative w-56 bg-gray-900 text-gray-300 flex flex-col shrink-0 h-full">
            <button
              onClick={() => setSidebarOpen(false)}
              className="absolute top-4 right-4 text-gray-400 hover:text-white"
              aria-label="Close menu"
            >
              <X size={20} />
            </button>
            {sidebarContent}
          </aside>
        </div>
      )}

      {/* Desktop sidebar */}
      <aside
        className="hidden md:flex w-56 bg-gray-900 text-gray-300 flex-col shrink-0"
        aria-label="Sidebar navigation"
      >
        {sidebarContent}
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto pt-14 md:pt-0" aria-label="Page content">
        <div className="max-w-7xl mx-auto px-6 py-8 animate-page-in">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
