"""Composite a generated image back onto its source through an edit mask.

codex's built-in ``image_gen`` has no inpainting/mask parameter — it always
re-renders the whole frame. To still honour "只改涂抹区" we run the model on the
full frame (steered by a visual guide image, see ``lib/maskGuide.ts``) and then
composite here: pixels OUTSIDE the painted region are copied from the original,
byte for byte, so only the masked area can differ.

Mask convention matches the frontend editor and the OpenAI images/edits API:
the mask's **alpha** channel marks the editable region — alpha 0 (transparent)
= repaint here, alpha 255 (opaque) = keep the original. A mask saved without an
alpha channel falls back to luminance (white = repaint), the usual convention
for flattened masks.
"""

from __future__ import annotations

import logging

from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

# Softens the seam between kept and repainted pixels. Scaled to the image so it
# behaves the same on a 1024px and a 4096px frame.
FEATHER_RATIO = 0.004
MIN_FEATHER_PX = 1.0


def _edit_weight_map(mask: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Greyscale map: 255 where the model's output should win, 0 where the
    original must be preserved."""
    if mask.size != size:
        # Nearest keeps the painted region's hard edge intact; feathering below
        # is what softens it, not the resampling.
        mask = mask.resize(size, Image.NEAREST)

    if "A" in mask.getbands():
        alpha = mask.getchannel("A")
        # editable = transparent → invert alpha.
        return alpha.point(lambda a: 255 - a)

    logger.info("mask has no alpha channel; falling back to luminance (white = repaint)")
    return mask.convert("L")


def composite_with_mask(
    base_path: str,
    generated_path: str,
    mask_path: str,
    out_path: str,
) -> str:
    """Write ``out_path`` = base outside the mask, generated inside it.

    The generated image is resized to the base's dimensions when the model
    returns a different aspect/size, so the result always matches the source
    frame the user drew the mask on.
    """
    base = Image.open(base_path).convert("RGB")
    generated = Image.open(generated_path).convert("RGB")
    mask = Image.open(mask_path)

    if generated.size != base.size:
        generated = generated.resize(base.size, Image.LANCZOS)

    weight = _edit_weight_map(mask, base.size)

    feather = max(MIN_FEATHER_PX, min(base.size) * FEATHER_RATIO)
    weight = weight.filter(ImageFilter.GaussianBlur(radius=feather))

    # composite(a, b, m) == a where m is 255, b where m is 0.
    Image.composite(generated, base, weight).save(out_path)
    return out_path
