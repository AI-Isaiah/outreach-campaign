import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Queue from "./pages/Queue";
import CampaignList from "./pages/CampaignList";
import CampaignDetail from "./pages/CampaignDetail";
import ContactList from "./pages/ContactList";
import ContactDetail from "./pages/ContactDetail";
import Templates from "./pages/Templates";
import CompanyDetail from "./pages/CompanyDetail";
import Settings from "./pages/Settings";
import Insights from "./pages/Insights";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/campaigns" element={<CampaignList />} />
          <Route path="/campaigns/:name" element={<CampaignDetail />} />
          <Route path="/contacts" element={<ContactList />} />
          <Route path="/contacts/:id" element={<ContactDetail />} />
          <Route path="/templates" element={<Templates />} />
          <Route path="/companies/:id" element={<CompanyDetail />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
