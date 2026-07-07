// Mounts the ported amazon-image-studio (src/imagegen, MIT © Ali-Aria) as a
// full-screen route. Image generation and Listing planning are routed to
// eco_listing's codex backend (no API key). The studio has no concept of a
// "run", so we inject the current runId for the backend calls.
import { useParams } from 'react-router-dom';
import ImagegenApp from '../imagegen/App';
import { getEcoRunId, setEcoRunId } from '../imagegen/lib/ecoBackend';
import '../imagegen/index.css';
import 'streamdown/styles.css';
import 'katex/dist/katex.min.css';

export default function ImageStudioPort() {
  const { runId } = useParams<{ runId: string }>();
  // Set synchronously during render (not in an effect) on purpose: the studio's
  // deeply-nested components read this runId in their OWN mount effects, and React
  // runs child effects BEFORE a parent effect here — so a useEffect would set it
  // too late and break the Listing auto-fill. The write is idempotent (same runId
  // across re-renders), so it's safe under StrictMode / concurrent renders.
  if (getEcoRunId() !== (runId ?? null)) setEcoRunId(runId ?? null);

  return (
    <div className="imagegen-scope" style={{ minHeight: '100vh', background: 'hsl(var(--background))' }}>
      <ImagegenApp />
    </div>
  );
}
