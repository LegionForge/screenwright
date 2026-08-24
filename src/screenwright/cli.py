from __future__ import annotations

import asyncio
import hashlib
import tomllib
from pathlib import Path
from typing import Optional

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from screenwright.capture import FlowResult, run_flow
from screenwright.config import Flow, ScreenwrightConfig, load_config
from screenwright.output import write_flow_output, write_root_readme
from screenwright.vision import describe

app = typer.Typer(
    name="screenwright",
    help="Documentation screenshot pipeline — capture UI flows and generate markdown output.",
    add_completion=False,
)
console = Console()


def _resolve_output(config_output: str, override: Optional[Path]) -> Path:
    return override if override else Path(config_output)


def _format_validation_errors(exc: ValidationError) -> list[str]:
    """Render pydantic's error list as short "field.path: message" lines.

    Drops the docs-URL footer pydantic appends per error — useful in a
    library traceback, just noise in a CLI error list.
    """
    lines = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "(root)"
        lines.append(f"{loc}: {err['msg']}")
    return lines


def _load_config_or_exit(config_path: Path) -> ScreenwrightConfig:
    """Load config.toml, or print a clean error and exit — never a raw traceback.

    Shared by run/flows/validate so a bad TOML (syntax error or a schema
    violation like an invalid step field) fails the same clear way no
    matter which command hit it.
    """
    if not config_path.exists():
        console.print(f"[red]Config not found:[/red] {config_path}")
        raise typer.Exit(1)

    try:
        return load_config(config_path)
    except tomllib.TOMLDecodeError as exc:
        console.print(f"[red]TOML syntax error in {config_path}:[/red] {exc}")
        raise typer.Exit(1) from None
    except ValidationError as exc:
        console.print(f"[red]Config validation failed ({config_path}):[/red]")
        for line in _format_validation_errors(exc):
            console.print(f"  [red]•[/red] {line}")
        raise typer.Exit(1) from None


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_pngs(flow_dir: Path) -> dict[str, str]:
    """Hash every existing PNG in a flow's output dir, keyed by filename.

    Taken *before* a flow runs (which overwrites files at the same paths),
    so it captures the previous run's state to diff the new one against.
    """
    if not flow_dir.is_dir():
        return {}
    return {p.name: _hash_file(p) for p in flow_dir.glob("*.png")}


async def _process_flow(
    flow_def: Flow,
    cfg: ScreenwrightConfig,
    output_root: Path,
    progress: Progress,
    semaphore: asyncio.Semaphore,
    check: bool,
) -> tuple[FlowResult, list[str]]:
    """Run one flow, describe its captures, and write its output.

    The progress task is created only after the semaphore is acquired
    (not upfront for all flows) so that with the default concurrency=1
    this produces the exact same one-task-at-a-time progress display as
    before concurrency existed — no visible behavior change for the
    default case, only for opt-in --concurrency > 1.

    Returns (result, changed_capture_names) — changed_capture_names is
    always [] when check=False (no hashing done, no overhead for the
    common case).
    """
    async with semaphore:
        task = progress.add_task(f"Running flow: [bold]{flow_def.name}[/bold]", total=None)
        before = _snapshot_pngs(output_root / flow_def.name) if check else {}
        result = await run_flow(flow_def, cfg, output_root)

        if cfg.vision_describe and result.captures:
            progress.update(
                task,
                description=f"Describing screenshots: [bold]{flow_def.name}[/bold]",
            )
            for capture in result.captures:
                try:
                    # describe() is synchronous (sync vendor SDK clients) —
                    # run it off the event loop so it doesn't block other
                    # flows running concurrently under --concurrency > 1.
                    capture.metadata = await asyncio.to_thread(describe, capture.path, cfg.vision)
                except Exception as exc:
                    # A single bad describe() call (API blip, bad key,
                    # provider outage) must not abort every remaining
                    # capture in this flow or every remaining flow in
                    # the run — leave metadata unset (output.py already
                    # tolerates that) and keep going.
                    console.print(
                        f"[yellow]Warning:[/yellow] describe failed for "
                        f"{capture.capture_name!r}: {exc}"
                    )

        write_flow_output(result, output_root)

        changed: list[str] = []
        if check:
            for capture in result.captures:
                if before.get(capture.path.name) != _hash_file(capture.path):
                    changed.append(capture.capture_name)

        if result.error:
            progress.update(
                task,
                completed=True,
                description=f"[yellow]Partial:[/yellow] {flow_def.name} — {result.error}",
            )
        else:
            progress.update(
                task,
                completed=True,
                description=f"[green]Done:[/green] {flow_def.name}",
            )
        return result, changed


async def _run_flows(
    flows_to_run: list[Flow],
    cfg: ScreenwrightConfig,
    output_root: Path,
    concurrency: int,
    check: bool,
) -> list[tuple[FlowResult, list[str]]]:
    semaphore = asyncio.Semaphore(concurrency)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        return await asyncio.gather(
            *(
                _process_flow(flow_def, cfg, output_root, progress, semaphore, check)
                for flow_def in flows_to_run
            )
        )


@app.command()
def run(
    config_path: Path = typer.Argument(..., help="Path to TOML config file"),
    flow: Optional[str] = typer.Option(None, "--flow", "-f", help="Run a single named flow"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Override output directory from config"
    ),
    concurrency: int = typer.Option(
        1,
        "--concurrency",
        "-j",
        help="Run up to N flows concurrently (default 1 = sequential, same as before this "
        "option existed). Each flow launches its own browser, so raise this cautiously.",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        "-c",
        help="Exit 1 if any screenshot's bytes differ from the previous run in the same "
        "output directory (exact SHA256 diff, not perceptual). Pairs with the deterministic "
        "capture options (animations='disabled' by default, mask) — if a page has residual "
        "non-determinism, tighten those rather than expecting fuzzy tolerance here. A first "
        "run with no prior output reports every capture as changed; that's expected.",
    ),
) -> None:
    """Execute screenshot flows defined in a TOML config file."""
    cfg = _load_config_or_exit(config_path)
    output_root = _resolve_output(cfg.output_dir, output)
    output_root.mkdir(parents=True, exist_ok=True)

    if concurrency < 1:
        console.print("[red]--concurrency must be at least 1.[/red]")
        raise typer.Exit(1)

    flows_to_run = cfg.flows
    if flow:
        target = cfg.get_flow(flow)
        if target is None:
            console.print(f"[red]Flow not found:[/red] {flow!r}")
            console.print(f"Available: {', '.join(cfg.flow_names())}")
            raise typer.Exit(1)
        flows_to_run = [target]

    if not flows_to_run:
        console.print("[yellow]No flows defined in config.[/yellow]")
        raise typer.Exit(0)

    outcomes = asyncio.run(_run_flows(flows_to_run, cfg, output_root, concurrency, check))
    all_results = [result for result, _ in outcomes]

    write_root_readme(all_results, output_root)

    total_captures = sum(len(r.captures) for r in all_results)
    total_videos = sum(1 for r in all_results if r.video_path is not None)
    failed_flows = [r for r in all_results if r.error]
    console.print(
        f"\n[green]Captured {total_captures} screenshot(s) across "
        f"{len(all_results)} flow(s).[/green]"
    )
    if failed_flows:
        console.print(
            f"[yellow]{len(failed_flows)} flow(s) stopped early "
            "(partial output was still written):[/yellow]"
        )
        for r in failed_flows:
            console.print(f"  [yellow]•[/yellow] {r.flow_name}: {r.error}")
    if total_videos:
        console.print(f"[green]Recorded {total_videos} video(s).[/green]")
    console.print(f"Output: [bold]{output_root}[/bold]")

    if check:
        changed_by_flow = {result.flow_name: changed for result, changed in outcomes if changed}
        if changed_by_flow:
            console.print("\n[yellow]Screenshot changes detected:[/yellow]")
            for flow_name, changed in changed_by_flow.items():
                for capture_name in changed:
                    console.print(f"  [yellow]•[/yellow] {flow_name}/{capture_name}")
            raise typer.Exit(1)
        console.print("\n[green]No screenshot changes detected.[/green]")


@app.command()
def flows(
    config_path: Path = typer.Argument(..., help="Path to TOML config file"),
) -> None:
    """List flows defined in a config file."""
    cfg = _load_config_or_exit(config_path)
    if not cfg.flows:
        console.print("[yellow]No flows defined.[/yellow]")
        return

    for flow_def in cfg.flows:
        captures = sum(1 for s in flow_def.steps if s.action == "capture")
        console.print(
            f"  [bold]{flow_def.name}[/bold] — {len(flow_def.steps)} steps, {captures} capture(s)"
        )


@app.command()
def validate(
    config_path: Path = typer.Argument(..., help="Path to TOML config file"),
) -> None:
    """Check a config file for TOML syntax errors and schema violations, without running it.

    Catches everything Screenwright's Pydantic models validate at load time
    (invalid step fields, path-traversal names, secret=true without an
    ${ENV_VAR} value, etc.) in under a second — fast feedback compared to
    finding out 40 seconds into a browser run that a flow was misconfigured.
    Does not verify that selectors actually resolve on the live page; that
    requires navigating each flow's URLs, which this intentionally doesn't
    do (no side effects, no network dependency, works offline).
    """
    cfg = _load_config_or_exit(config_path)

    total_steps = sum(len(f.steps) for f in cfg.flows)
    total_captures = sum(1 for f in cfg.flows for s in f.steps if s.action == "capture")
    console.print(
        f"[green]Valid.[/green] {len(cfg.flows)} flow(s), {total_steps} step(s), "
        f"{total_captures} capture(s)."
    )
