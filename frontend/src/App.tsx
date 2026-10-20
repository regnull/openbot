import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import SaveNotification from "./components/SaveNotification";
import CustomCaret from "./components/CustomCaret";
import Layout from "./components/Layout";
import ApiKeyGate from "./components/ApiKeyGate";
import BackendFallback from "./components/BackendFallback";
import SetupGate from "./components/SetupGate";
import InboxPage from "./pages/InboxPage";
import ThreadsPage from "./pages/ThreadsPage";
import ThreadPage from "./pages/ThreadPage";
import BotsPage from "./pages/BotsPage";
import BotEditorPage from "./pages/BotEditorPage";
import BotPage from "./pages/BotPage";
import SettingsPage from "./pages/SettingsPage";
import ScheduledPage from "./pages/ScheduledPage";
import DocumentTitle from "./components/DocumentTitle";
import { Spinner } from "./components/ui";

// Internal 3D character lab: lazy so three.js stays out of the main bundle, and outside the
// backend gates because it only needs static assets.
const OpenlingsLabPage = lazy(() => import("./pages/OpenlingsLabPage"));
const OfficeLabPage = lazy(() => import("./pages/OfficeLabPage"));

export default function App() {
  return (
    <>
    <DocumentTitle />
    <Routes>
      <Route path="/lab/openlings" element={
        <Suspense fallback={<div className="flex h-dvh items-center justify-center"><Spinner /></div>}><OpenlingsLabPage /></Suspense>
      } />
      <Route path="/lab/office" element={
        <Suspense fallback={<div className="flex h-dvh items-center justify-center"><Spinner /></div>}><OfficeLabPage /></Suspense>
      } />
      <Route path="*" element={<MainApp />} />
    </Routes>
    </>
  );
}

function MainApp() {
  return (
    <>
    <CustomCaret />
    <SaveNotification />
    <ApiKeyGate>
      <BackendFallback>
        <SetupGate>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/inbox" replace />} />
            <Route path="/inbox" element={<InboxPage />} />
            <Route path="/threads" element={<ThreadsPage />} />
            <Route path="/threads/:id" element={<ThreadPage />} />
            <Route path="/bots" element={<BotsPage />} />
            <Route path="/bots/new" element={<BotEditorPage />} />
            <Route path="/bots/:id" element={<BotPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/scheduled" element={<ScheduledPage />} />
          </Route>
        </Routes>
        </SetupGate>
      </BackendFallback>
    </ApiKeyGate>
    </>
  );
}
