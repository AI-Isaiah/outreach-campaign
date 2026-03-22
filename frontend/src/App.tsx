import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import RequireAuth from "./components/RequireAuth";
import Layout from "./components/Layout";
import { SkeletonCard } from "./components/Skeleton";

// Auth pages (eager-loaded — tiny)
import Login from "./pages/Login";
import Register from "./pages/Register";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";

// Eager-load the campaigns list (landing page)
import CampaignList from "./pages/CampaignList";

// Lazy-load all other pages for code splitting
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Queue = lazy(() => import("./pages/Queue"));
const CampaignDetail = lazy(() => import("./pages/CampaignDetail"));
const CampaignBuilder = lazy(() => import("./pages/CampaignBuilder"));
const CampaignWizard = lazy(() => import("./pages/CampaignWizard"));
const ContactList = lazy(() => import("./pages/ContactList"));
const ContactDetail = lazy(() => import("./pages/ContactDetail"));
const Templates = lazy(() => import("./pages/Templates"));
const CompanyDetail = lazy(() => import("./pages/CompanyDetail"));
const Settings = lazy(() => import("./pages/Settings"));
const Insights = lazy(() => import("./pages/Insights"));
const Pipeline = lazy(() => import("./pages/Pipeline"));
const Inbox = lazy(() => import("./pages/Inbox"));
const NewsletterList = lazy(() => import("./pages/NewsletterList"));
const NewsletterComposer = lazy(() => import("./pages/NewsletterComposer"));
const ImportWizard = lazy(() => import("./pages/ImportWizard"));
const Research = lazy(() => import("./pages/Research"));
const ResearchJobDetail = lazy(() => import("./pages/ResearchJobDetail"));
const ResearchResultDetail = lazy(() => import("./pages/ResearchResultDetail"));

function PageFallback() {
  return (
    <div className="py-8 space-y-6">
      <div className="h-7 w-48 bg-gray-200 rounded animate-pulse" />
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    </div>
  );
}

function Page({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <Suspense fallback={<PageFallback />}>{children}</Suspense>
    </ErrorBoundary>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <Suspense fallback={<PageFallback />}>
          <Routes>
            {/* Public auth routes */}
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />

            {/* Protected app routes */}
            <Route
              element={
                <RequireAuth>
                  <Layout />
                </RequireAuth>
              }
            >
              <Route path="/" element={<Page><CampaignList /></Page>} />
              <Route path="/queue" element={<Page><Queue /></Page>} />
              <Route path="/campaigns" element={<Navigate to="/" replace />} />
              <Route path="/campaigns/new" element={<Page><CampaignBuilder /></Page>} />
              <Route path="/campaigns/wizard" element={<Page><CampaignWizard /></Page>} />
              <Route path="/campaigns/:name" element={<Page><CampaignDetail /></Page>} />
              <Route path="/dashboard" element={<Page><Dashboard /></Page>} />
              <Route path="/contacts" element={<Page><ContactList /></Page>} />
              <Route path="/contacts/:id" element={<Page><ContactDetail /></Page>} />
              <Route path="/templates" element={<Page><Templates /></Page>} />
              <Route path="/companies/:id" element={<Page><CompanyDetail /></Page>} />
              <Route path="/settings" element={<Page><Settings /></Page>} />
              <Route path="/insights" element={<Page><Insights /></Page>} />
              <Route path="/pipeline" element={<Page><Pipeline /></Page>} />
              <Route path="/inbox" element={<Page><Inbox /></Page>} />
              <Route path="/newsletters" element={<Page><NewsletterList /></Page>} />
              <Route path="/newsletters/new" element={<Page><NewsletterComposer /></Page>} />
              <Route path="/newsletters/:id" element={<Page><NewsletterComposer /></Page>} />
              <Route path="/research" element={<Page><Research /></Page>} />
              <Route path="/research/:id" element={<Page><ResearchJobDetail /></Page>} />
              <Route path="/research/results/:id" element={<Page><ResearchResultDetail /></Page>} />
              <Route path="/import" element={<Page><ImportWizard /></Page>} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </BrowserRouter>
  );
}
