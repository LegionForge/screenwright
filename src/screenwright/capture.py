from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from screenwright.config import (
    CaptureStep,
    CheckStep,
    ClickStep,
    FillStep,
    Flow,
    HoverStep,
    NavigateStep,
    PressStep,
    ScreenwrightConfig,
    SelectStep,
    WaitStep,
)


@dataclass
class CaptureResult:
    flow_name: str
    capture_name: str
    path: Path
    metadata: Optional[object] = None  # ScreenshotMetadata, set after capture by caller


@dataclass
class FlowResult:
    flow_name: str
    captures: list[CaptureResult] = field(default_factory=list)
    video_path: Optional[Path] = None
    video_mp4_path: Optional[Path] = None


class FfmpegNotFoundError(RuntimeError):
    """Raised when record_mp4 is set but ffmpeg is not on PATH."""


async def _convert_to_mp4(webm_path: Path) -> Path:
    if shutil.which("ffmpeg") is None:
        raise FfmpegNotFoundError(
            "record_mp4 = true requires ffmpeg on PATH (e.g. `brew install ffmpeg`)."
        )
    mp4_path = webm_path.with_suffix(".mp4")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(webm_path),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(mp4_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {stderr.decode(errors='replace')}")
    return mp4_path


async def _capture_page_or_element(page: Page, output_path: Path, selector: str | None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if selector:
        element = await page.query_selector(selector)
        if element is None:
            raise ValueError(f"Selector not found: {selector!r}")
        await element.screenshot(path=str(output_path))
    else:
        await page.screenshot(path=str(output_path), full_page=True)


async def capture_single_url(
    url: str,
    output_path: Path,
    selector: str | None = None,
    wait_until: str = "load",
) -> Path:
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch()
        page: Page = await browser.new_page()
        await page.goto(url, wait_until=wait_until)
        await _capture_page_or_element(page, output_path, selector)
        await browser.close()
    return output_path


async def run_flow(
    flow: Flow,
    config: ScreenwrightConfig,
    output_root: Path,
) -> FlowResult:
    result = FlowResult(flow_name=flow.name)
    flow_dir = output_root / flow.name
    flow_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch()

        context: Optional[BrowserContext] = None
        if flow.record:
            context = await browser.new_context(
                record_video_dir=str(flow_dir),
                record_video_size={"width": flow.record_width, "height": flow.record_height},
            )
            page = await context.new_page()
        else:
            page = await browser.new_page()

        for step in flow.steps:
            if isinstance(step, NavigateStep):
                url = step.url
                if url.startswith("/"):
                    url = config.base_url.rstrip("/") + url
                await page.goto(url, wait_until=step.wait_until)

            elif isinstance(step, CaptureStep):
                out = flow_dir / f"{step.name}.png"
                await _capture_page_or_element(page, out, step.selector)
                result.captures.append(
                    CaptureResult(
                        flow_name=flow.name,
                        capture_name=step.name,
                        path=out,
                    )
                )

            elif isinstance(step, FillStep):
                await page.fill(step.selector, step.value)

            elif isinstance(step, ClickStep):
                await page.click(step.selector)

            elif isinstance(step, WaitStep):
                await asyncio.sleep(step.ms / 1000)

            elif isinstance(step, HoverStep):
                await page.hover(step.selector)

            elif isinstance(step, PressStep):
                await page.press(step.selector, step.key)

            elif isinstance(step, CheckStep):
                if step.checked:
                    await page.check(step.selector)
                else:
                    await page.uncheck(step.selector)

            elif isinstance(step, SelectStep):
                await page.select_option(step.selector, step.value)

        if context is not None:
            video = page.video
            await page.close()
            await context.close()
            if video is not None:
                raw_path = Path(await video.path())
                final_path = flow_dir / f"{flow.name}.webm"
                raw_path.replace(final_path)
                result.video_path = final_path
                if flow.record_mp4:
                    result.video_mp4_path = await _convert_to_mp4(final_path)

        await browser.close()

    return result
