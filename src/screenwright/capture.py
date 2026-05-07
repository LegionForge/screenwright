from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from playwright.async_api import Browser, Page, async_playwright

from screenwright.config import (
    CaptureStep,
    ClickStep,
    FillStep,
    Flow,
    HoverStep,
    NavigateStep,
    PressStep,
    ScreenwrightConfig,
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


async def _capture_page_or_element(
    page: Page, output_path: Path, selector: str | None
) -> None:
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
) -> Path:
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch()
        page: Page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")
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
        page: Page = await browser.new_page()

        for step in flow.steps:
            if isinstance(step, NavigateStep):
                url = step.url
                if url.startswith("/"):
                    url = config.base_url.rstrip("/") + url
                await page.goto(url, wait_until="networkidle")

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

        await browser.close()

    return result
