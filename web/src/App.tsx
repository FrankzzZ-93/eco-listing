import { Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from './components/layout/AppLayout';
import InputPage from './pages/InputPage';
import RunDashboard from './pages/RunDashboard';
import ImageStudio from './pages/ImageStudio';
import PromptsPage from './pages/PromptsPage';
import SettingsPage from './pages/SettingsPage';

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/new" replace />} />
        <Route path="/new" element={<InputPage />} />
        <Route path="/run/:runId" element={<RunDashboard />} />
        <Route path="/run/:runId/images" element={<ImageStudio />} />
        <Route path="/run/:runId/:tab" element={<RunDashboard />} />
        <Route path="/prompts" element={<PromptsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
