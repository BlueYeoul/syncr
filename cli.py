"""syncr - Local → Server file sync CLI."""

import os
import sys
import time
import getpass
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich import print as rprint

from .config import (
    get_server_config, list_servers, save_server, delete_server,
    get_local_config, save_local_config,
    get_ignore_patterns, init_ignore_file,
    LOCAL_CONFIG_FILE,
)
from .sync import sync_files, test_connection
from .watcher import start_watching

console = Console()


@click.group()
@click.version_option("0.1.0", prog_name="syncr")
def main():
    """syncr — sync local project files to a remote server over SSH."""
    pass


# ─── server management ───────────────────────────────────────────────────────

@main.group()
def server():
    """Manage server profiles."""
    pass


@server.command("add")
@click.argument("profile")
def server_add(profile: str):
    """Add a new server profile."""
    console.print(f"\n[bold cyan]Adding server profile:[/bold cyan] {profile}\n")

    host = Prompt.ask("Host (IP or hostname)")
    port = Prompt.ask("Port", default="22")
    user = Prompt.ask("Username")
    auth = Prompt.ask("Auth method", choices=["password", "key"], default="key")

    config = {
        "host": host,
        "port": int(port),
        "user": user,
        "auth": auth,
    }

    if auth == "key":
        key_path = Prompt.ask("SSH key path", default="~/.ssh/id_rsa")
        config["key_path"] = key_path
    else:
        save_pw = Confirm.ask("Save password? (not recommended)", default=False)
        if save_pw:
            pw = getpass.getpass("Password: ")
            config["password"] = pw

    save_server(profile, config)
    console.print(f"\n[green]✓[/green] Server profile [bold]{profile}[/bold] saved.")

    if Confirm.ask("Test connection now?", default=True):
        console.print("Testing connection...")
        if test_connection(config):
            console.print("[green]✓ Connection successful![/green]")
        else:
            console.print("[red]✗ Connection failed. Check your settings.[/red]")


@server.command("list")
def server_list():
    """List all saved server profiles."""
    servers = list_servers()
    if not servers:
        console.print("[yellow]No server profiles saved. Run [bold]syncr server add <name>[/bold][/yellow]")
        return

    table = Table(title="Saved Servers", show_header=True)
    table.add_column("Profile", style="bold cyan")
    table.add_column("Host")
    table.add_column("Port")
    table.add_column("User")
    table.add_column("Auth")

    for name, cfg in servers.items():
        table.add_row(
            name,
            cfg.get("host", ""),
            str(cfg.get("port", 22)),
            cfg.get("user", ""),
            cfg.get("auth", "key"),
        )
    console.print(table)


@server.command("remove")
@click.argument("profile")
def server_remove(profile: str):
    """Remove a server profile."""
    if delete_server(profile):
        console.print(f"[green]✓[/green] Removed profile [bold]{profile}[/bold].")
    else:
        console.print(f"[red]Profile '{profile}' not found.[/red]")


@server.command("test")
@click.argument("profile")
def server_test(profile: str):
    """Test connection to a server profile."""
    cfg = get_server_config(profile)
    if not cfg:
        console.print(f"[red]Profile '{profile}' not found.[/red]")
        return
    console.print(f"Testing connection to [bold]{profile}[/bold]...")
    if test_connection(cfg):
        console.print("[green]✓ Connection successful![/green]")
    else:
        console.print("[red]✗ Connection failed.[/red]")


# ─── project init ─────────────────────────────────────────────────────────────

@main.command()
@click.option("--server", "-s", "profile", help="Server profile to use")
@click.option("--remote", "-r", help="Remote project path")
def init(profile: Optional[str], remote: Optional[str]):
    """Initialize syncr in the current project directory."""
    console.print("\n[bold cyan]Initializing syncr for this project[/bold cyan]\n")

    local_path = str(Path.cwd())

    # Choose server profile
    servers = list_servers()
    if not servers:
        console.print("[yellow]No server profiles found. Add one first:[/yellow]")
        console.print("  [bold]syncr server add <name>[/bold]")
        return

    if not profile:
        if len(servers) == 1:
            profile = list(servers.keys())[0]
            console.print(f"Using server profile: [bold]{profile}[/bold]")
        else:
            profile = Prompt.ask(
                "Server profile",
                choices=list(servers.keys()),
                default=list(servers.keys())[0],
            )

    if not remote:
        remote = Prompt.ask("Remote project path (absolute)", default=f"/home/{servers[profile]['user']}/projects/{Path.cwd().name}")

    config = {
        "server": profile,
        "local_path": local_path,
        "remote_path": remote,
    }
    save_local_config(config)

    # Create .syncrignore
    created = init_ignore_file()
    if created:
        console.print(f"[green]✓[/green] Created [bold].syncrignore[/bold]")

    console.print(f"[green]✓[/green] Created [bold]{LOCAL_CONFIG_FILE}[/bold]")
    console.print(f"\n  Local:  [dim]{local_path}[/dim]")
    console.print(f"  Remote: [dim]{servers[profile]['host']}:{remote}[/dim]")
    console.print(f"\nRun [bold cyan]syncr push[/bold cyan] for initial sync, or [bold cyan]syncr watch[/bold cyan] to auto-sync.")


# ─── push ─────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--server", "-s", "profile", help="Override server profile")
@click.option("--dry-run", is_flag=True, help="Show what would be synced")
def push(profile: Optional[str], dry_run: bool):
    """Sync all project files to the server (full push)."""
    local_cfg = get_local_config()
    if not local_cfg:
        console.print("[red]Not initialized. Run [bold]syncr init[/bold] first.[/red]")
        return

    profile = profile or local_cfg.get("server")
    server_cfg = get_server_config(profile)
    if not server_cfg:
        console.print(f"[red]Server profile '{profile}' not found.[/red]")
        return

    local_root = Path(local_cfg["local_path"])
    remote_root = local_cfg["remote_path"]
    ignore_patterns = get_ignore_patterns()

    console.print(f"\n[bold]Pushing[/bold] → [cyan]{server_cfg['host']}:{remote_root}[/cyan]")

    if dry_run:
        from .sync import get_all_files
        files = get_all_files(local_root, ignore_patterns)
        console.print(f"\n[dim]Would sync {len(files)} files:[/dim]")
        for f in files:
            console.print(f"  [dim]{f}[/dim]")
        return

    start = time.time()
    synced, errors = sync_files(local_root, remote_root, server_cfg, ignore_patterns)
    elapsed = time.time() - start

    console.print(f"\n[bold]Done.[/bold] {synced} files synced, {errors} errors — {elapsed:.1f}s")


# ─── watch ────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--server", "-s", "profile", help="Override server profile")
@click.option("--debounce", default=1.0, help="Debounce delay in seconds (default: 1.0)")
def watch(profile: Optional[str], debounce: float):
    """Watch for file changes and auto-sync to the server."""
    local_cfg = get_local_config()
    if not local_cfg:
        console.print("[red]Not initialized. Run [bold]syncr init[/bold] first.[/red]")
        return

    profile = profile or local_cfg.get("server")
    server_cfg = get_server_config(profile)
    if not server_cfg:
        console.print(f"[red]Server profile '{profile}' not found.[/red]")
        return

    local_root = Path(local_cfg["local_path"])
    remote_root = local_cfg["remote_path"]
    ignore_patterns = get_ignore_patterns()

    console.print(f"\n[bold cyan]syncr watch[/bold cyan] started")
    console.print(f"  Local:  [dim]{local_root}[/dim]")
    console.print(f"  Remote: [dim]{server_cfg['host']}:{remote_root}[/dim]")
    console.print(f"  Press [bold]Ctrl+C[/bold] to stop.\n")

    def on_change(changed_files):
        timestamp = time.strftime("%H:%M:%S")
        console.print(f"[dim]{timestamp}[/dim] [yellow]↺[/yellow] {len(changed_files)} file(s) changed — syncing...")
        synced, errors = sync_files(
            local_root, remote_root, server_cfg, ignore_patterns,
            changed_files=changed_files, verbose=True,
        )
        if errors == 0:
            console.print(f"  [green]✓[/green] Synced {synced} file(s)\n")
        else:
            console.print(f"  [yellow]⚠[/yellow] Synced {synced}, {errors} error(s)\n")

    observer = start_watching(local_root, ignore_patterns, on_change, debounce)

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        observer.stop()
        console.print("\n[dim]Watcher stopped.[/dim]")
    observer.join()


# ─── status ───────────────────────────────────────────────────────────────────

@main.command()
def status():
    """Show current project sync configuration."""
    local_cfg = get_local_config()
    if not local_cfg:
        console.print("[yellow]No .syncr.toml found in this directory.[/yellow]")
        console.print("Run [bold]syncr init[/bold] to set up.")
        return

    profile = local_cfg.get("server", "?")
    server_cfg = get_server_config(profile)

    console.print(f"\n[bold]syncr status[/bold]")
    console.print(f"  Profile:  [cyan]{profile}[/cyan]")
    if server_cfg:
        console.print(f"  Server:   {server_cfg['user']}@{server_cfg['host']}:{server_cfg.get('port', 22)}")
        console.print(f"  Auth:     {server_cfg.get('auth', 'key')}")
    console.print(f"  Local:    {local_cfg.get('local_path', '.')}")
    console.print(f"  Remote:   {local_cfg.get('remote_path', '?')}")

    ignore_patterns = get_ignore_patterns()
    console.print(f"  Ignoring: {len(ignore_patterns)} patterns\n")
