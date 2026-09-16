import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ApiKeyGate from "./components/ApiKeyGate";
import BackendFallback from "./components/BackendFallback";
import InboxPage from "./pages/InboxPage";
import ThreadsPage from "./pages/ThreadsPage";
import ThreadPage from "./pages/ThreadPage";
import BotsPage from "./pages/BotsPage";
import BotEditorPage from "./pages/BotEditorPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  return (
    <ApiKeyGate>
      <BackendFallback>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/inbox" replace />} />
            <Route path="/inbox" element={<InboxPage />} />
            <Route path="/threads" element={<ThreadsPage />} />
            <Route path="/threads/:id" element={<ThreadPage />} />
            <Route path="/bots" element={<BotsPage />} />
            <Route path="/bots/new" element={<BotEditorPage />} />
            <Route path="/bots/:id" element={<BotEditorPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BackendFallback>
    </ApiKeyGate>
  );
}
