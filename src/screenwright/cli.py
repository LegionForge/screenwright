from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from screenwright.capture import run_flow
from screenwright.config import load_config
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


@app.command()
def run(
    config_path: Path = typer.Argument(..., help="Path to TOML config file"),
    flow: Optional[str] = typer.Option(None, "--flow", "-f", help="Run a single named flow"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Override output directory from config"
    ),
) -> None:
    """Execute screenshot flows defined in a TOML config file."""
    if not config_path.exists():
        console.print(f"[red]Config not found:[/red] {config_path}")
        raise typer.Exit(1)

    cfg = load_config(config_path)
    output_root = _resolve_output(cfg.output_dir, output)
    output_root.mkdir(parents=True, exist_ok=True)

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

    all_results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for flow_def in flows_to_run:
            task = progress.add_task(f"Running flow: [bold]{flow_def.name}[/bold]", total=None)
            result = asyncio.run(run_flow(flow_def, cfg, output_root))

            if cfg.vision_describe and result.captures:
                progress.update(
                    task,
                    description=f"Describing screenshots: [bold]{flow_def.name}[/bold]",
                )
                for capture in result.captures:
                    capture.metadata = describe(capture.path, cfg.vision)

            write_flow_output(result, output_root)
            all_results.append(result)
            progress.update(
                task,
                completed=True,
                description=f"[green]Done:[/green] {flow_def.name}",
            )

    write_root_readme(all_results, output_root)

    total_captures = sum(len(r.captures) for r in all_results)
    total_videos = sum(1 for r in all_results if r.video_path is not None)
    console.print(
        f"\n[green]Captured {total_captures} screenshot(s) across "
        f"{len(all_results)} flow(s).[/green]"
    )
    if total_videos:
        console.print(f"[green]Recorded {total_videos} video(s).[/green]")
    console.print(f"Output: [bold]{output_root}[/bold]")


@app.command()
def flows(
    config_path: Path = typer.Argument(..., help="Path to TOML config file"),
) -> None:
    """List flows defined in a config file."""
    if not config_path.exists():
        console.print(f"[red]Config not found:[/red] {config_path}")
        raise typer.Exit(1)

    cfg = load_config(config_path)
    if not cfg.flows:
        console.print("[yellow]No flows defined.[/yellow]")
        return

    for flow_def in cfg.flows:
        captures = sum(1 for s in flow_def.steps if s.action == "capture")
        console.print(
            f"  [bold]{flow_def.name}[/bold] — {len(flow_def.steps)} steps, {captures} capture(s)"
        )
