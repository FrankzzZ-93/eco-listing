"""AI 商品图生成工具。

复用 codex CLI 的内置 ``image_gen`` 工具生成图片——走 ChatGPT 订阅认证
（``~/.codex/auth.json`` 的 OAuth），**无需 OPENAI_API_KEY**。我们通过
``codex exec``（见 :mod:`app.tools.codex_exec`）下发一段提示词，明确要求 codex：

1. 使用内置 ``image_gen`` 工具（不是 PIL 画图、不是需要 key 的 CLI fallback）；
2. 把每张图保存到我们指定的绝对路径下；
3. 最后输出一行 JSON ``{"saved": [...]}`` 汇报保存路径。

图片落盘到 ``artifacts/{run_id}/generated/``，通过 ``/artifacts`` 静态访问。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Optional

from app.config import settings
from app.tools.codex_exec import CodexExecError, codex_exec
from app.tools.file_store import to_artifact_url

logger = logging.getLogger(__name__)

# Repo-vendored chroma-key helper (scripts/remove_chroma_key.py). Referenced by
# absolute path + the backend's own interpreter so the white-bg step does not
# rely on codex's bundled skill or on bash-only shell expansion (broke on
# Windows). image_gen_tool.py lives at app/tools/, so repo root is three up.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REMOVE_CHROMA_KEY_SCRIPT = os.path.join(_REPO_ROOT, "scripts", "remove_chroma_key.py")
# Absolute path to the running backend's Python (has Pillow); falls back to
# "python3" on the PATH if sys.executable is somehow empty.
_PYTHON = sys.executable or "python3"


class ImageGenError(RuntimeError):
    """An image-generation failure that carries a downloadable full-detail log.

    ``log_url`` points at an ``/artifacts/...`` text file holding the prompt and
    the complete codex output/traceback, so a failure on another machine can be
    diagnosed end-to-end (the inline message is kept short for the UI)."""

    def __init__(self, message: str, log_url: Optional[str] = None):
        super().__init__(message)
        self.log_url = log_url

# 内置 image_gen 工具支持的尺寸（gpt-image-2）。前端只暴露常用几档。
ALLOWED_SIZES = {
    "1024x1024",
    "1536x1024",
    "1024x1536",
    "2048x2048",
    "auto",
}
DEFAULT_SIZE = "1024x1024"
MAX_IMAGES = 6
# gpt-image-2 quality levels exposed by the built-in image_gen tool.
ALLOWED_QUALITIES = {"low", "medium", "high", "auto"}
DEFAULT_QUALITY = "high"


def _generated_dir(run_id: str) -> str:
    d = os.path.join(settings.artifacts_dir, run_id, "generated")
    os.makedirs(d, exist_ok=True)
    return d


def _write_failure_log(run_id: str, name: str, content: str) -> str:
    """Persist a full image-gen failure report under the run's generated dir and
    return its ``/artifacts`` URL (served statically, so it's downloadable)."""
    path = os.path.join(_generated_dir(run_id), f"imagegen_{name}.log")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        logger.warning("could not write image-gen failure log %s", path, exc_info=True)
        return ""
    return to_artifact_url(path)


def _build_prompt(
    user_prompt: str,
    *,
    target_paths: list[str],
    size: str,
    quality: str,
    reference_paths: list[str],
    white_bg: bool,
) -> str:
    """构造下发给 codex 的提示词，锁定内置 image_gen 工具。"""
    n = len(target_paths)
    lines: list[str] = [
        "You are generating product images for an Amazon listing.",
        "",
        "## Hard rules (must follow)",
        "- Use the built-in `image_gen` tool to generate REAL photorealistic images.",
        "- Do NOT draw or synthesize the product with code (no shapes via PIL/canvas/SVG/matplotlib). Post-processing of a generated image (chroma-key removal, compositing, flatten, resize) with PIL is allowed.",
        "- Do NOT use the CLI fallback (scripts/image_gen.py) and do NOT use or ask for OPENAI_API_KEY.",
        f"- Target size for every image: {size}.",
        f"- Quality: {quality}.",
    ]

    if reference_paths:
        ref_list = "\n".join(f"  - {p}" for p in reference_paths)
        lines += [
            "",
            "## Reference images",
            "Load each of these local files with the built-in `view_image` tool FIRST,",
            "then generate using them as references. Keep the SAME product identity",
            "(shape, color, material, proportions, branding) consistent with the references.",
            ref_list,
        ]

    if white_bg:
        lines += [
            "",
            "## Background — pure white via chroma-key (Amazon main image)",
            "Produce a perfectly clean PURE WHITE (#FFFFFF) background using the chroma-key workflow:",
            "  1. Generate the product on a perfectly flat solid #00ff00 chroma-key background"
            " (use #ff00ff instead if the product itself is green/teal). No shadows, gradients,"
            " texture, reflections, floor plane, or lighting variation; crisp edges; generous"
            " padding; never use the key color anywhere in the product.",
            '  2. Remove the key color locally by running this EXACT command (absolute paths,'
            " works on any OS — do NOT substitute a different python or script path):",
            f'     "{_PYTHON}" "{REMOVE_CHROMA_KEY_SCRIPT}"'
            " --input <generated> --out <cutout.png> --auto-key border --soft-matte --despill",
            "  3. Composite the cutout onto a solid #FFFFFF background (flatten the alpha) and save"
            " the FINAL flattened white-background image to the target path below. No props, no"
            " text, no watermark.",
        ]

    lines += [
        "",
        "## Primary request",
        user_prompt.strip(),
        "",
        "## Output files",
        f"Generate {n} image(s). Save each generated image to EXACTLY these absolute path(s),"
        " moving/copying from the default $CODEX_HOME location as needed:",
    ]
    for i, p in enumerate(target_paths, 1):
        lines.append(f"  {i}. {p}")
    lines += [
        "",
        "After saving, output ONLY this JSON on the final line (no markdown fences):",
        '{"saved": [' + ", ".join(f'"{p}"' for p in target_paths) + "]}",
    ]
    return "\n".join(lines)


def _parse_saved_paths(raw: str) -> list[str]:
    """从 codex JSONL 输出里解析最后一个 agent_message 的 {"saved": [...]}。"""
    for line in reversed([l for l in raw.splitlines() if l.strip()]):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or obj.get("type") != "item.completed":
            continue
        item = obj.get("item") or {}
        if item.get("type") not in ("agent_message", "message"):
            continue
        text = (item.get("text") or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        saved = payload.get("saved") if isinstance(payload, dict) else None
        if isinstance(saved, list):
            return [str(p) for p in saved]
    return []


async def generate_images(
    run_id: str,
    prompt: str,
    *,
    n: int = 1,
    size: str = DEFAULT_SIZE,
    quality: str = DEFAULT_QUALITY,
    reference_paths: Optional[list[str]] = None,
    white_bg: bool = False,
    job_id: Optional[str] = None,
) -> list[str]:
    """生成 ``n`` 张图片，返回可访问的 ``/artifacts`` URL 列表。

    Args:
        run_id: 关联的 run（决定落盘目录）。
        prompt: 用户的生图描述。
        n: 生成张数（1..MAX_IMAGES）。
        size: 图片尺寸（见 ALLOWED_SIZES）。
        quality: 出图质量（见 ALLOWED_QUALITIES）。
        reference_paths: 参考图的本地绝对路径（用于产品一致性）。
        white_bg: 是否要求纯白底（亚马逊主图）。
        job_id: 关联的图片任务 id（仅用于命名失败日志）。

    Raises:
        ValueError: 入参非法。
        ImageGenError: codex 子进程失败 / 未产出图片 / 白底脚本缺失；``.log_url``
            指向落盘的完整报错日志。
    """
    if not prompt or not prompt.strip():
        raise ValueError("生图提示词不能为空")
    n = max(1, min(int(n), MAX_IMAGES))
    if size not in ALLOWED_SIZES:
        size = DEFAULT_SIZE
    if quality not in ALLOWED_QUALITIES:
        quality = DEFAULT_QUALITY

    refs = [p for p in (reference_paths or []) if p and os.path.isfile(p)]
    out_dir = os.path.abspath(_generated_dir(run_id))
    ts = int(time.time())
    log_name = job_id or str(ts)
    # Absolute target paths so codex writes to the exact place regardless of its
    # cwd, and so they line up with the writable-root we hand codex below.
    target_paths = [os.path.join(out_dir, f"{ts}_{i + 1}.png") for i in range(n)]

    # White-bg needs the vendored chroma-key helper. Fail fast with a precise,
    # logged error if it's missing rather than letting codex silently produce
    # nothing (the original Windows failure mode).
    if white_bg and not os.path.isfile(REMOVE_CHROMA_KEY_SCRIPT):
        msg = f"白底后处理脚本缺失：{REMOVE_CHROMA_KEY_SCRIPT}（请确认仓库 scripts/ 完整）"
        log_url = _write_failure_log(run_id, log_name, msg)
        logger.error("image_gen white_bg helper missing run=%s: %s", run_id, REMOVE_CHROMA_KEY_SCRIPT)
        raise ImageGenError(msg, log_url=log_url)

    codex_prompt = _build_prompt(
        prompt,
        target_paths=target_paths,
        size=size,
        quality=quality,
        reference_paths=refs,
        white_bg=white_bg,
    )

    logger.info(
        "image_gen start run=%s job=%s n=%d size=%s quality=%s refs=%d white_bg=%s",
        run_id, log_name, n, size, quality, len(refs), white_bg,
    )

    try:
        # Image generation must WRITE the finished PNG to our output dir. Codex's
        # default sandbox is read-only, which lets the built-in image_gen source
        # be created but blocks the shell chroma-key/move step from saving into
        # the project (observed: "Read-only file system"). Grant workspace-write
        # plus our output dir as an explicit writable root.
        raw = await codex_exec(
            codex_prompt,
            sandbox="workspace-write",
            writable_roots=[out_dir],
        )
    except CodexExecError as e:
        # codex 子进程本身失败（二进制缺失 / 未登录 / 非零退出 / 超时）。把完整
        # 报错连同提示词落盘成可下载日志，inline 只留简短信息。
        detail = (
            f"image_gen run={run_id} job={log_name} white_bg={white_bg}\n"
            f"=== ERROR ===\n{type(e).__name__}: {e}\n\n"
            f"=== PROMPT ===\n{codex_prompt}\n"
        )
        log_url = _write_failure_log(run_id, log_name, detail)
        logger.error("image_gen codex_exec failed run=%s job=%s: %s", run_id, log_name, e, exc_info=True)
        raise ImageGenError(f"codex 生图子进程失败：{type(e).__name__}: {e}", log_url=log_url) from e

    # 优先以"我们指定的目标路径是否真的落盘"为准（最稳），其次回退到 JSON 解析。
    produced = [p for p in target_paths if os.path.isfile(p)]
    if not produced:
        for p in _parse_saved_paths(raw):
            if os.path.isfile(p):
                produced.append(p)

    if not produced:
        # codex 正常退出但没有图片落盘——常见于白底后处理脚本/路径出错。把 codex 的
        # 完整输出 + 提示词落盘成可下载日志，方便在其他设备（含 Windows）排查。
        detail = (
            f"image_gen run={run_id} job={log_name} white_bg={white_bg}\n"
            f"=== RESULT ===\ncodex 正常退出 (rc=0) 但目标路径无图片落盘。\n"
            f"target_paths:\n" + "\n".join(f"  - {p}" for p in target_paths) + "\n\n"
            f"=== PROMPT ===\n{codex_prompt}\n\n"
            f"=== CODEX FULL OUTPUT ({len(raw)} chars) ===\n{raw}\n"
        )
        log_url = _write_failure_log(run_id, log_name, detail)
        tail = raw[-600:].strip() or "(codex 无输出)"
        logger.error(
            "image_gen produced no files run=%s job=%s white_bg=%s; tail=%s",
            run_id, log_name, white_bg, tail,
        )
        raw_lower = raw.lower()
        read_only = "read-only file system" in raw_lower or "read only" in raw_lower
        # codex explicitly reports when its session has no built-in image_gen tool
        # (varies by codex version / account / model). Detect it so the error is
        # actionable instead of a generic "no image produced".
        image_gen_unavailable = "image_gen" in raw_lower and "not available" in raw_lower
        if image_gen_unavailable:
            cause = (
                "该机器的 codex 会话未提供内置 image_gen 工具（我们已禁用需要 OPENAI_API_KEY 的 "
                "CLI 兜底）。请在该机器上升级 codex 到较新版本（npm i -g @openai/codex@latest）、"
                "确认内置 imagegen 技能存在（~/.codex/skills/.system/imagegen/）且账号支持图片生成。"
            )
        elif read_only:
            cause = "codex 沙箱只读，无法写盘（已默认 workspace-write，若仍报只读请升级 codex 或检查其沙箱配置）。"
        elif white_bg:
            cause = "常见原因：白底后处理脚本执行失败（缺 Pillow 或路径错）。"
        else:
            cause = "可能 codex 未实际调用 image_gen 工具。"
        hint = "codex 正常退出但未产出图片。" + cause + f" codex 输出末尾：\n{tail}"
        raise ImageGenError(hint, log_url=log_url)

    urls = [to_artifact_url(p) for p in produced]
    logger.info("image_gen done run=%s job=%s produced=%d", run_id, log_name, len(urls))
    return urls


def list_generated_images(run_id: str) -> list[dict[str, str]]:
    """列举某个 run 已生成的图片，按文件名（含时间戳）倒序。"""
    out_dir = os.path.join(settings.artifacts_dir, run_id, "generated")
    if not os.path.isdir(out_dir):
        return []
    items: list[dict[str, str]] = []
    for name in sorted(os.listdir(out_dir), reverse=True):
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        items.append({
            "name": name,
            "url": f"/artifacts/{run_id}/generated/{name}",
        })
    return items
