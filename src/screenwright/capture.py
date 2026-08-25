from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenwright.config import (
    ENV_REF_RE,
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

_NAV_MAX_RETRIES = 2
_NAV_BACKOFF_BASE_SECONDS = 1.0


def _is_transient_navigation_error(exc: Exception) -> bool:
    """Best-effort check for retryable navigation failures.

    Deliberately conservative, mirroring vision.py's `_is_transient`: a
    navigation timeout or a `net::ERR_*` failure (DNS hiccup, connection
    reset, temporary refusal) can clear on retry; anything else (a 404, a
    malformed URL) is a real error that retrying just delays reporting.
    """
    if isinstance(exc, PlaywrightTimeoutError):
        return True
    return isinstance(exc, PlaywrightError) and "net::ERR_" in str(exc)


async def _goto_with_retry(page: Page, url: str, wait_until: str) -> None:
    for attempt in range(_NAV_MAX_RETRIES + 1):
        try:
            await page.goto(url, wait_until=wait_until)
            return
        except Exception as exc:
            if attempt == _NAV_MAX_RETRIES or not _is_transient_navigation_error(exc):
                raise
            await asyncio.sleep(_NAV_BACKOFF_BASE_SECONDS * (2**attempt))


def _resolve_fill_value(value: str) -> str:
    """Resolve a ${ENV_VAR} reference; pass through any other value as a literal.

    Only whole-value references are supported (``value = "${API_TOKEN}"``),
    not partial interpolation inside a longer string — that keeps the syntax
    unambiguous and the failure mode (unset var) a clean error rather than a
    string with a literal "${...}" typed into the page.
    """
    match = ENV_REF_RE.fullmatch(value)
    if match is None:
        return value
    var_name = match.group(1)
    resolved = os.environ.get(var_name)
    if resolved is None:
        raise ValueError(f"Environment variable {var_name!r} is not set.")
    return resolved


@dataclass
class CaptureResult:
    flow_name: str
    capture_name: str
    path: Path
    metadata: Optional[object] = None  # ScreenshotMetadata, set after capture by caller
    accessibility_path: Optional[Path] = None
    pdf_path: Optional[Path] = None


@dataclass
class FlowResult:
    flow_name: str
    captures: list[CaptureResult] = field(default_factory=list)
    video_path: Optional[Path] = None
    video_mp4_path: Optional[Path] = None
    har_path: Optional[Path] = None
    failed_step_index: Optional[int] = None
    error: Optional[str] = None


class FfmpegNotFoundError(RuntimeError):
    """Raised when record_mp4 is set but ffmpeg is not on PATH."""


_MP4_CONVERSION_TIMEOUT_SECONDS = 300.0


async def _convert_to_mp4(
    webm_path: Path, timeout_seconds: float = _MP4_CONVERSION_TIMEOUT_SECONDS
) -> Path:
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
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        # A hung/runaway ffmpeg process (a malformed .webm, a pathological
        # codec edge case) must not be left running — a leaked subprocess —
        # or block this call forever. Kill and reap it before reporting,
        # the same "never leave a resource dangling on a failure path"
        # discipline capture_single_url's browser.close() and run_flow's
        # finally block already follow for the browser process itself.
        proc.kill()
        await proc.wait()
        raise RuntimeError(
            f"ffmpeg conversion of {webm_path} timed out after {timeout_seconds}s and was killed."
        ) from None
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {stderr.decode(errors='replace')}")
    return mp4_path


async def _capture_page_or_element(
    page: Page,
    output_path: Path,
    selector: str | None,
    animations: str = "disabled",
    mask: list[str] | None = None,
    mask_color: str | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mask_locators = [page.locator(s) for s in mask] if mask else None
    if selector:
        element = await page.query_selector(selector)
        if element is None:
            raise ValueError(f"Selector not found: {selector!r}")
        await element.screenshot(
            path=str(output_path),
            animations=animations,
            mask=mask_locators,
            mask_color=mask_color,
        )
    else:
        await page.screenshot(
            path=str(output_path),
            full_page=True,
            animations=animations,
            mask=mask_locators,
            mask_color=mask_color,
        )


async def capture_single_url(
    url: str,
    output_path: Path,
    selector: str | None = None,
    wait_until: str = "load",
    timeout_ms: int = 30000,
    viewport_width: int = 1280,
    viewport_height: int = 720,
    animations: str = "disabled",
    mask: list[str] | None = None,
    mask_color: str | None = None,
) -> Path:
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch()
        try:
            page: Page = await browser.new_page(
                viewport={"width": viewport_width, "height": viewport_height}
            )
            page.set_default_timeout(timeout_ms)
            await _goto_with_retry(page, url, wait_until)
            await _capture_page_or_element(
                page,
                output_path,
                selector,
                animations=animations,
                mask=mask,
                mask_color=mask_color,
            )
        finally:
            # A bad selector (or a navigation failure after retries are
            # exhausted) used to skip this close entirely, leaking the
            # Chromium process — a real risk on the MCP surface, where an
            # agent plausibly retries capture_url/capture_element with a
            # different selector after a "Selector not found" error, each
            # failed attempt leaking one more browser. run_flow already
            # guarantees this via its own try/finally; this function never
            # had the same guarantee.
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

        viewport = {"width": flow.viewport_width, "height": flow.viewport_height}
        har_path = flow_dir / f"{flow.name}.har" if flow.har else None
        context: Optional[BrowserContext] = None
        page: Optional[Page] = None
        try:
            if flow.record:
                context = await browser.new_context(
                    viewport=viewport,
                    storage_state=flow.storage_state,
                    record_video_dir=str(flow_dir),
                    record_video_size={"width": flow.record_width, "height": flow.record_height},
                    record_har_path=str(har_path) if har_path else None,
                )
                page = await context.new_page()
            else:
                page = await browser.new_page(
                    viewport=viewport,
                    storage_state=flow.storage_state,
                    record_har_path=str(har_path) if har_path else None,
                )
            page.set_default_timeout(flow.timeout_ms)
        except Exception as exc:
            # A bad storage_state path is the likeliest failure here, but
            # this covers any browser/context/page setup error — none of
            # this was wrapped before, so a failure at this point used to
            # propagate out of run_flow as an unhandled exception, breaking
            # the "always return a FlowResult, never raise" contract the
            # per-step error handling below establishes.
            result.error = f"Failed to start browser session: {exc}"

        steps_to_run = enumerate(flow.steps) if page is not None else []
        for index, step in steps_to_run:
            try:
                if isinstance(step, NavigateStep):
                    url = step.url
                    if url.startswith("/"):
                        url = config.base_url.rstrip("/") + url
                    await _goto_with_retry(page, url, step.wait_until)

                elif isinstance(step, CaptureStep):
                    for variant in step.variants or [None]:
                        suffix = f"-{variant.name}" if variant is not None else ""
                        if variant is not None:
                            if (
                                variant.viewport_width is not None
                                or variant.viewport_height is not None
                            ):
                                await page.set_viewport_size(
                                    {
                                        "width": variant.viewport_width
                                        if variant.viewport_width is not None
                                        else flow.viewport_width,
                                        "height": variant.viewport_height
                                        if variant.viewport_height is not None
                                        else flow.viewport_height,
                                    }
                                )
                            # Always resolve color_scheme explicitly (never
                            # skip the call when unset) — otherwise a
                            # variant that doesn't set color_scheme inherits
                            # whatever an *earlier* variant in this same
                            # step's loop left active, contradicting the
                            # documented "unset falls back to light"
                            # contract (Variant's own docstring). This is
                            # the same class of bug as the post-step
                            # restore fix below, one level finer-grained:
                            # that fix resets state after all variants
                            # finish; this one resets it between each one.
                            color_scheme = (
                                variant.color_scheme
                                if variant.color_scheme is not None
                                else "light"
                            )
                            await page.emulate_media(color_scheme=color_scheme)

                        out = flow_dir / f"{step.name}{suffix}.png"
                        await _capture_page_or_element(
                            page,
                            out,
                            step.selector,
                            animations=step.animations,
                            mask=step.mask,
                            mask_color=step.mask_color,
                        )
                        accessibility_path = None
                        if step.accessibility_snapshot:
                            accessibility_path = flow_dir / f"{step.name}{suffix}.aria.yaml"
                            accessibility_path.write_text(
                                await page.aria_snapshot(), encoding="utf-8"
                            )
                        pdf_path = None
                        if step.pdf:
                            pdf_path = flow_dir / f"{step.name}{suffix}.pdf"
                            await page.pdf(path=str(pdf_path))
                        result.captures.append(
                            CaptureResult(
                                flow_name=flow.name,
                                capture_name=f"{step.name}{suffix}",
                                path=out,
                                accessibility_path=accessibility_path,
                                pdf_path=pdf_path,
                            )
                        )

                    if step.variants:
                        # Restore flow defaults so later steps in this flow
                        # aren't left running under a variant's viewport/
                        # color-scheme — emulate_media(color_scheme=None)
                        # does NOT reset to default, it's a no-op, so this
                        # must be an explicit value.
                        await page.set_viewport_size(
                            {"width": flow.viewport_width, "height": flow.viewport_height}
                        )
                        await page.emulate_media(color_scheme="light")

                elif isinstance(step, FillStep):
                    await page.fill(step.selector, _resolve_fill_value(step.value))

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
            except Exception as exc:  # noqa: BLE001 - reported on the result, not swallowed
                result.failed_step_index = index
                result.error = f"Step {index} ({step.action}) failed: {exc}"
                break

        # Always finalize video/HAR and close the browser, even if a step
        # above failed — otherwise a mid-flow error both loses the whole
        # recording (.webm/.har only flush on page/context close, not on
        # browser.close() alone) and leaks the browser process. This runs
        # whether or not the loop above broke early. Closing the page
        # explicitly (not just relying on browser.close() to sweep it up)
        # is required for HAR even when record=false and there's no
        # separate context to close — verified directly against the
        # installed Playwright before relying on it.
        try:
            if page is not None:
                try:
                    video = page.video if context is not None else None
                    await page.close()
                    if context is not None:
                        await context.close()
                    if video is not None:
                        raw_path = Path(await video.path())
                        final_path = flow_dir / f"{flow.name}.webm"
                        raw_path.replace(final_path)
                        result.video_path = final_path
                        if flow.record_mp4:
                            try:
                                result.video_mp4_path = await _convert_to_mp4(final_path)
                            except Exception as exc:
                                # Missing ffmpeg or a failed conversion must
                                # not crash the whole call and lose the
                                # .webm/captures that already succeeded —
                                # report it on the result instead, same
                                # "always return a FlowResult, never raise"
                                # contract the step loop and setup path
                                # already follow.
                                mp4_error = f"mp4 conversion failed: {exc}"
                                result.error = (
                                    f"{result.error}; {mp4_error}" if result.error else mp4_error
                                )
                    if har_path is not None:
                        result.har_path = har_path
                except Exception as exc:
                    # page.close()/context.close()/video.path()/the .webm
                    # rename can all raise (a full disk, a page that
                    # crashed mid-flow, a Playwright internal error) — this
                    # was the one piece of the finalize block still able to
                    # propagate out of run_flow unhandled, breaking the
                    # same "never raise" contract the mp4-conversion fix
                    # above already established for this block. Captures
                    # already written and any error from the step loop
                    # stay intact; this is reported alongside, not instead.
                    finalize_error = f"Failed to finalize video/HAR: {exc}"
                    result.error = (
                        f"{result.error}; {finalize_error}" if result.error else finalize_error
                    )
        finally:
            await browser.close()

    return result
