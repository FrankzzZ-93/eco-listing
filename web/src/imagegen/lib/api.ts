import { appendOutputResolutionToPrompt, type CallApiOptions, type CallApiResult } from './imageApiShared'
import { generateViaCodex } from './ecoBackend'

export type { CallApiOptions, CallApiResult } from './imageApiShared'
export { normalizeBaseUrl } from './devProxy'

// eco_listing integration: image generation goes through our FastAPI backend,
// which drives the codex CLI built-in image_gen tool (no API key). The upstream
// OpenAI / fal / custom-provider paths are bypassed.
export async function callImageApi(opts: CallApiOptions): Promise<CallApiResult> {
  const prompt = appendOutputResolutionToPrompt(opts.prompt, opts.params.size)
  const requestOpts = prompt === opts.prompt ? opts : { ...opts, prompt }
  return generateViaCodex(requestOpts)
}
