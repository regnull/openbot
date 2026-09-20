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

export default function App() {
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
          </Route>
        </Routes>
        </SetupGate>
      </BackendFallback>
    </ApiKeyGate>
    </>
  );
}
