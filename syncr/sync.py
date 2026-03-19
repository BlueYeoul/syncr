"""SSH-based file sync engine."""

import os
import fnmatch
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
import paramiko
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

console = Console()

# 병렬 전송 worker 수 (SSH 연결 수와 동일)
MAX_WORKERS = 8


def should_ignore(path: str, patterns: list[str]) -> bool:
    """Check if a path matches any ignore pattern."""
    path = path.lstrip("./").rstrip("/")
    path_obj = Path(path)
    name = path_obj.name
    parts = path_obj.parts

    for raw_pattern in patterns:
        pattern = raw_pattern.rstrip("/")
        if not pattern:
            continue
        if fnmatch.fnmatch(name, pattern):
            return True
        if fnmatch.fnmatch(path, pattern):
            return True
        for part in parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def get_all_files(local_root: Path, ignore_patterns: list[str]) -> list[Path]:
    """
    Recursively collect files, pruning ignored dirs early so
    os.walk never descends into them.
    """
    files = []
    for root, dirs, filenames in os.walk(local_root):
        rel_root = os.path.relpath(root, local_root)
        if rel_root == ".":
            rel_root = ""

        # ── Prune dirs in-place ──────────────────────────────────────────────
        # This is the key: ignored directories are removed from `dirs` so
        # os.walk never descends into them at all.
        dirs[:] = [
            d for d in dirs
            if not should_ignore(
                os.path.join(rel_root, d) if rel_root else d,
                ignore_patterns,
            )
        ]

        for fname in filenames:
            rel_path = os.path.join(rel_root, fname) if rel_root else fname
            if not should_ignore(rel_path, ignore_patterns):
                files.append(Path(rel_path))

    return files


def connect_ssh(server_config: dict) -> paramiko.SSHClient:
    """Establish SSH connection from server config."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    kwargs = {
        "hostname": server_config["host"],
        "port": server_config.get("port", 22),
        "username": server_config["user"],
    }

    auth_method = server_config.get("auth", "password")
    if auth_method == "key":
        key_path = server_config.get("key_path", "~/.ssh/id_rsa")
        kwargs["key_filename"] = os.path.expanduser(key_path)
    else:
        password = server_config.get("password")
        if password:
            kwargs["password"] = password
        else:
            import getpass
            kwargs["password"] = getpass.getpass(
                f"Password for {server_config['user']}@{server_config['host']}: "
            )

    client.connect(**kwargs)
    return client


def ensure_remote_dir(sftp: paramiko.SFTPClient, remote_path: str):
    """Recursively create remote directories if they don't exist."""
    parts = Path(remote_path).parts
    current = ""
    for part in parts:
        current = os.path.join(current, part) if current else part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


def _make_remote_dirs(server_config: dict, remote_dirs: set[str]):
    """Pre-create all needed remote directories via a single SSH connection."""
    client = connect_ssh(server_config)
    sftp = client.open_sftp()
    for d in sorted(remote_dirs):  # sorted = parents before children
        try:
            sftp.stat(d)
        except FileNotFoundError:
            try:
                sftp.mkdir(d)
            except Exception:
                pass  # parent may not exist yet; ensure_remote_dir handles it
    sftp.close()
    client.close()


def _upload_worker(
    args: tuple,
) -> tuple[str, Optional[Exception]]:
    """Upload a single file. Returns (rel_path_str, error_or_None)."""
    local_file, remote_file, remote_dir, server_config = args
    try:
        client = connect_ssh(server_config)
        sftp = client.open_sftp()
        ensure_remote_dir(sftp, remote_dir)
        sftp.put(str(local_file), remote_file)
        sftp.close()
        client.close()
        return (str(local_file), None)
    except Exception as e:
        return (str(local_file), e)


def sync_files(
    local_root: Path,
    remote_root: str,
    server_config: dict,
    ignore_patterns: list[str],
    changed_files: Optional[list[Path]] = None,
    verbose: bool = True,
) -> tuple[int, int]:
    """
    Sync files from local to remote using a parallel connection pool.

    Args:
        changed_files: If provided, only sync these specific files.
                       If None, sync all files (full sync).

    Returns:
        (synced_count, error_count)
    """
    # ── 1. Collect files to sync ─────────────────────────────────────────────
    if changed_files is not None:
        files_to_sync = [
            f for f in changed_files
            if not should_ignore(str(f), ignore_patterns)
        ]
    else:
        if verbose:
            console.print("[dim]Scanning local files...[/dim]", end="\r")
        files_to_sync = get_all_files(local_root, ignore_patterns)

    if not files_to_sync:
        if verbose:
            console.print("[dim]No files to sync.[/dim]")
        return 0, 0

    if verbose:
        console.print(f"[dim]Found {len(files_to_sync)} files to sync.[/dim]")

    # ── 2. Build upload task list ─────────────────────────────────────────────
    tasks = []
    for rel_path in files_to_sync:
        local_file = local_root / rel_path
        remote_file = os.path.join(remote_root, str(rel_path))
        remote_dir = os.path.dirname(remote_file)
        tasks.append((local_file, remote_file, remote_dir, server_config))

    # ── 3. Parallel upload ────────────────────────────────────────────────────
    synced = 0
    errors = 0
    workers = min(MAX_WORKERS, len(tasks))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("Syncing...", total=len(tasks))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_upload_worker, t): t for t in tasks}
            for future in as_completed(futures):
                local_file, remote_file, remote_dir, _ = futures[future]
                rel = os.path.relpath(str(local_file), str(local_root))
                local_path_str, err = future.result()
                if err is None:
                    synced += 1
                    if verbose:
                        console.print(f"  [green]✓[/green] {rel}")
                else:
                    errors += 1
                    console.print(f"  [red]✗[/red] {rel}: {err}")
                progress.advance(task_id)

    return synced, errors


def test_connection(server_config: dict) -> bool:
    """Test SSH connection."""
    try:
        client = connect_ssh(server_config)
        client.close()
        return True
    except Exception as e:
        console.print(f"[red]Connection failed:[/red] {e}")
        return False