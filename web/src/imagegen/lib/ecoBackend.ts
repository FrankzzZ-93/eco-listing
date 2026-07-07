// Bridges the ported studio to eco_listing's FastAPI backend, which generates
// images through the codex CLI built-in image_gen tool (no API key). Replaces
// the upstream browser→OpenAI path. The studio has no concept of a "run", so the
// host route (ImageStudioPort) injects the current runId here.

import type { CallApiOptions, CallApiResult } from './imageApiShared'

let ecoRunId: string | null = null

export function setEcoRunId(runId: string | null) {
  ecoRunId = runId
}

export function getEcoRunId(): string | null {
  return ecoRunId
}

function apiBase(): string {
  const runId = ecoRunId
  if (!runId) throw new Error('未关联到具体任务（缺少 runId），无法调用生图后端')
  return `/api/runs/${encodeURIComponent(runId)}`
}

// codex/gpt-image-2 supported sizes. Anything else (e.g. the studio's 4K
// 4096x4096) falls back to auto so the backend doesn't reject it.
const SUPPORTED_SIZES = new Set(['1024x1024', '1536x1024', '1024x1536', '2048x2048', 'auto'])
function normalizeSize(size: string): string {
  return SUPPORTED_SIZES.has(size) ? size : 'auto'
}

// Polling bounds so a dead/unreachable backend can't spin the loop forever.
const POLL_INTERVAL_MS = 2500
const POLL_MAX_MS = 12 * 60 * 1000 // codex runs ~1-3 min; generous ceiling
const POLL_MAX_ERRORS = 8 // consecutive job-status failures before giving up

interface ImageJob {
  id: string
  status: 'running' | 'completed' | 'failed'
  images: string[]
  error: string | null
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [meta, b64] = dataUrl.split(',')
  const mime = /data:([^;]+)/.exec(meta)?.[1] || 'image/png'
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new Blob([bytes], { type: mime })
}

async function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

async function fetchArtifactAsDataUrl(url: string, signal?: AbortSignal): Promise<string> {
  const res = await fetch(url, { signal, cache: 'no-store' })
  if (!res.ok) throw new Error(`结果图片下载失败：HTTP ${res.status}`)
  return blobToDataUrl(await res.blob())
}

async function uploadReference(dataUrl: string, signal?: AbortSignal): Promise<string> {
  const blob = dataUrlToBlob(dataUrl)
  const ext = blob.type.split('/')[1] || 'png'
  const form = new FormData()
  form.append('file', blob, `ref.${ext}`)
  const res = await fetch(`${apiBase()}/images/upload-reference`, { method: 'POST', body: form, signal })
  const data = res.ok ? ((await res.json().catch(() => null)) as { url?: string } | null) : null
  if (!res.ok || !data?.url) {
    // Surface the failure instead of silently generating without the reference —
    // references matter for keeping the product consistent.
    throw new Error('参考图上传失败，请重试或移除该参考图')
  }
  return data.url
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'))
    const t = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('Aborted', 'AbortError')) }, { once: true })
  })
}

/**
 * Generate images through the codex backend, adapting the studio's CallApiOptions
 * to our async job API and returning results in the shape the store expects.
 */
export async function generateViaCodex(opts: CallApiOptions): Promise<CallApiResult> {
  const base = apiBase()
  const { params, inputImageDataUrls, signal } = opts

  // Reference images (data URLs) → persisted /artifacts URLs the backend accepts.
  // uploadReference throws on failure, so a dropped reference surfaces to the user.
  const referenceUrls: string[] = []
  for (const dataUrl of inputImageDataUrls) {
    referenceUrls.push(await uploadReference(dataUrl, signal))
  }

  const body = {
    prompt: opts.prompt,
    n: params.n > 0 ? params.n : 1,
    size: normalizeSize(params.size),
    quality: params.quality === 'auto' ? 'high' : params.quality,
    reference_urls: referenceUrls,
    white_bg: false,
  }

  const startRes = await fetch(`${base}/images/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!startRes.ok) {
    const detail = await startRes.json().catch(() => null)
    throw new Error(detail?.detail || `生图请求失败：HTTP ${startRes.status}`)
  }
  const { job } = (await startRes.json()) as { job: ImageJob }

  // Poll the job to completion (codex runs 1-3 min; no streaming preview). Bounded
  // by a wall-clock deadline and a consecutive-error cap so a dead backend can't
  // loop forever — only signal-abort would otherwise stop it.
  const deadline = Date.now() + POLL_MAX_MS
  let consecutiveErrors = 0
  for (;;) {
    if (Date.now() > deadline) throw new Error('生图超时，请稍后在任务历史中查看或重试')
    await sleep(POLL_INTERVAL_MS, signal)

    let jobsRes: Response
    try {
      jobsRes = await fetch(`${base}/images/jobs`, { signal, cache: 'no-store' })
    } catch (err) {
      if (signal?.aborted) throw err
      if (++consecutiveErrors > POLL_MAX_ERRORS) throw new Error('无法连接生图后端，请确认服务已启动')
      continue
    }
    if (!jobsRes.ok) {
      if (++consecutiveErrors > POLL_MAX_ERRORS) throw new Error(`生图状态查询失败：HTTP ${jobsRes.status}`)
      continue
    }
    consecutiveErrors = 0

    const { jobs } = (await jobsRes.json()) as { jobs: ImageJob[] }
    const current = jobs.find((j) => j.id === job.id)
    if (!current || current.status === 'running') continue
    if (current.status === 'failed') throw new Error(current.error || '生图失败')

    const images: string[] = []
    for (const url of current.images) images.push(await fetchArtifactAsDataUrl(url, signal))
    if (!images.length) throw new Error('生图完成但未返回图片')
    return { images, rawImageUrls: current.images }
  }
}

/**
 * Run the Amazon Listing image planner through the codex backend. The studio
 * builds the system/user prompts + JSON Schema; we relay them and get back the
 * plan as a JSON string (fed into the studio's existing parse/normalize logic).
 */
export async function planViaCodex(args: {
  system: string
  user: string
  schema?: unknown
  signal?: AbortSignal
}): Promise<string> {
  const res = await fetch(`${apiBase()}/images/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ system: args.system, user: args.user, schema: args.schema ?? null }),
    signal: args.signal,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail || `AI 策划失败：HTTP ${res.status}`)
  }
  const data = (await res.json()) as { content?: string }
  if (!data.content) throw new Error('AI 策划未返回内容')
  return data.content
}

/**
 * Pull the run's completed Listing (title / bullets / description) from eco and
 * format it the way the planner's paste box expects, so the studio opens
 * pre-filled from the listing the user just generated. Returns null when there
 * is no run or no completed listing.
 */
export async function fetchEcoListingText(): Promise<string | null> {
  if (!ecoRunId) return null
  try {
    const res = await fetch(`${apiBase()}/final`, { cache: 'no-store' })
    if (!res.ok) return null
    const data = (await res.json()) as {
      final_listing?: { title?: string; bullet_points?: string[]; description?: string }
    }
    const l = data.final_listing
    if (!l) return null
    const lines: string[] = []
    if (l.title) lines.push(`Title: ${l.title}`)
    const bullets = l.bullet_points ?? []
    if (bullets.length) {
      lines.push('', 'About this item')
      for (const b of bullets) lines.push(`- ${b}`)
    }
    if (l.description) {
      const text = l.description.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
      if (text) lines.push('', text)
    }
    const out = lines.join('\n').trim()
    return out || null
  } catch {
    return null
  }
}

// Competitor product images captured during scraping — offered as references.
export async function fetchEcoCompetitorImageUrls(): Promise<string[]> {
  if (!ecoRunId) return []
  try {
    const res = await fetch(`${apiBase()}/competitor-images`, { cache: 'no-store' })
    if (!res.ok) return []
    const data = (await res.json()) as { competitors?: Array<{ images?: Array<{ url: string }> }> }
    return (data.competitors ?? []).flatMap((g) => (g.images ?? []).map((i) => i.url))
  } catch {
    return []
  }
}
