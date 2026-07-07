/// <reference types="vite/client" />

// Build-time constants injected via Vite `define` (see vite.config.ts). The
// ported image studio (src/imagegen) reads these; declared here so tsc resolves
// them across the whole web app.
declare const __APP_VERSION__: string;
declare const __DEV_PROXY_CONFIG__: string;
