// Turns an alpha mask into a "visual guide" image + prompt for the codex backend.
//
// codex's image_gen has no inpainting parameter, so the mask cannot be handed to
// the model directly. Instead we burn the painted region onto a copy of the
// source as a bright translucent overlay and tell the model, in words, that the
// marked area is the only thing it may change. That steers *what* gets painted;
// the backend's PIL composite (app/tools/mask_composite.py) is what actually
// guarantees the rest of the frame survives untouched.
//
// This mirrors upstream's Seedream editor approach (annotate + describe) rather
// than the OpenAI images/edits mask parameter, which we have no endpoint for.

import { loadImage } from './canvasImage'

// Magenta reads as an annotation in almost every product photo, and the prompt
// explicitly tells the model the colour is not part of the scene.
const GUIDE_RGB: [number, number, number] = [255, 0, 200]
const GUIDE_OPACITY = 0.45

/**
 * Draw the editable region (mask alpha < 255) over the source image.
 * Returns a PNG data URL, or null when the mask covers nothing.
 */
export async function createMaskGuideDataUrl(
  sourceDataUrl: string,
  maskDataUrl: string,
): Promise<string | null> {
  const [source, mask] = await Promise.all([loadImage(sourceDataUrl), loadImage(maskDataUrl)])

  const width = source.naturalWidth
  const height = source.naturalHeight
  if (!width || !height) return null

  // Read the mask's alpha into a standalone canvas so we can turn "transparent
  // means editable" into an opaque, visible overlay shape.
  const maskCanvas = document.createElement('canvas')
  maskCanvas.width = width
  maskCanvas.height = height
  const maskCtx = maskCanvas.getContext('2d', { willReadFrequently: true })
  if (!maskCtx) return null
  maskCtx.drawImage(mask, 0, 0, width, height)

  const maskData = maskCtx.getImageData(0, 0, width, height)
  const overlay = maskCtx.createImageData(width, height)
  let editablePixels = 0
  for (let i = 0; i < maskData.data.length; i += 4) {
    // alpha < 255 == painted == editable
    const editable = maskData.data[i + 3] < 255
    if (!editable) continue
    editablePixels++
    overlay.data[i] = GUIDE_RGB[0]
    overlay.data[i + 1] = GUIDE_RGB[1]
    overlay.data[i + 2] = GUIDE_RGB[2]
    overlay.data[i + 3] = 255
  }
  if (editablePixels === 0) return null

  const guide = document.createElement('canvas')
  guide.width = width
  guide.height = height
  const ctx = guide.getContext('2d')
  if (!ctx) return null

  ctx.drawImage(source, 0, 0, width, height)

  // Put the solid overlay shape on its own canvas, then stamp it translucently
  // so the underlying product stays readable through the marking.
  maskCtx.putImageData(overlay, 0, 0)
  ctx.save()
  ctx.globalAlpha = GUIDE_OPACITY
  ctx.drawImage(maskCanvas, 0, 0)
  ctx.restore()

  return guide.toDataURL('image/png')
}

/**
 * Wrap the user's instruction with the roles of each image we send, so the model
 * knows image 1 is the untouched baseline and image 2 marks the edit region.
 */
export function buildMaskEditPrompt(instruction: string, referenceCount: number): string {
  const lines = [
    '请执行一次精确的局部图片编辑。',
    '图1是必须编辑的原图，也是构图、画幅和未修改内容的唯一基准。',
    '图2是"编辑区域标注图"，其中洋红色半透明区域标出了唯一允许修改的范围；该颜色是标注，不是原图内容，也不是要生成的元素。',
  ]
  for (let i = 0; i < referenceCount; i++) {
    lines.push(`图${i + 3}是参考图${i + 1}，仅在编辑要求涉及替换、融合或风格/材质参考时使用。`)
  }
  lines.push(
    '',
    `用户的编辑要求：${instruction.trim()}`,
    '',
    '只修改标注范围内的内容；标注范围以外的主体、背景、透视、光照、文字与版式必须保持与图1完全一致。',
    '最终结果中不得出现任何洋红色标注、边框或涂鸦。',
    '保持图1的原始宽高比，只输出一张完成后的干净图片，不要输出对比图、拼图或说明文字。',
  )
  return lines.join('\n')
}
