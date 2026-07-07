import { Suspense, lazy } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from './components/layout/AppLayout';
import InputPage from './pages/InputPage';
import RunDashboard from './pages/RunDashboard';
import PromptsPage from './pages/PromptsPage';
import SettingsPage from './pages/SettingsPage';

// The ported studio pulls Tailwind + its own heavy deps; code-split it so its
// CSS/JS load only when the route is visited, keeping the Antd pages untouched.
const ImageStudioPort = lazy(() => import('./pages/ImageStudioPort'));

export default function App() {
  return (
    <Routes>
      {/* Full-screen ported studio: outside AppLayout so it owns the viewport.
          The studio ships full Tailwind incl. a global preflight reset; that's
          fine because the "生成商品图" button opens this route in a NEW TAB
          (window.open), so the studio's document is separate from the Ant Design
          app and its CSS never co-loads with the Antd pages. Avoid adding an
          in-app <Link> to /studio (same-tab nav would leak preflight into Antd). */}
      <Route
        path="/run/:runId/studio"
        element={
          <Suspense fallback={null}>
            <ImageStudioPort />
          </Suspense>
        }
      />
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/new" replace />} />
        <Route path="/new" element={<InputPage />} />
        <Route path="/run/:runId" element={<RunDashboard />} />
        <Route path="/run/:runId/:tab" element={<RunDashboard />} />
        <Route path="/prompts" element={<PromptsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
