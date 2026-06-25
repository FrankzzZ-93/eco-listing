// Client-side file download helpers.
//
// These force an actual "save file" instead of navigating the browser to the
// resource (which, for text/markdown or JSON served inline, just opens a new
// tab showing the content).

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke on the next tick so the click has a chance to start the download.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadText(filename: string, text: string, mime = 'text/plain'): void {
  triggerDownload(new Blob([text], { type: `${mime};charset=utf-8` }), filename);
}

export function downloadJson(filename: string, data: unknown): void {
  downloadText(filename, JSON.stringify(data, null, 2), 'application/json');
}

/**
 * Fetch a same-origin URL (e.g. an `/artifacts/...` file) and save it as a
 * real download. Falls back to opening the URL if the fetch fails.
 */
export async function downloadUrlAsFile(url: string, filename: string): Promise<void> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`下载失败 (${res.status})`);
  triggerDownload(await res.blob(), filename);
}

/** Serialize an array of flat row objects to CSV (RFC-4180 quoting). */
export function rowsToCsv(rows: Record<string, unknown>[], columns: { key: string; label: string }[]): string {
  const esc = (v: unknown): string => {
    const s = v === null || v === undefined ? '' : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const header = columns.map((c) => esc(c.label)).join(',');
  const body = rows.map((r) => columns.map((c) => esc(r[c.key])).join(',')).join('\n');
  // BOM so Excel opens UTF-8 (Chinese) correctly.
  return `﻿${header}\n${body}`;
}
