"""SSH-based file sync engine."""

import os
import fnmatch
from pathlib import Path
from typing import Optional
import paramiko
from rich.console import Console

console = Console()


def should_ignore(path: str, patterns: list[str]) -> bool:
    """
    Check if a path matches any ignore pattern.

    Handles:
      - exact name match:   "venv"   matches  "venv"  or  "a/venv/b"
      - trailing slash:     "data/"  matches  "data"  dir and its contents
      - glob patterns:      "*.pyc"  matches  "foo.pyc"
      - path patterns:      "a/b"    matches  "a/b/c.py"
    """
    # Normalize: strip leading ./ and trailing slashes from the input path
    path = path.lstrip("./").rstrip("/")
    path_obj = Path(path)
    name = path_obj.name          # last component
    parts = path_obj.parts        # all components

    for raw_pattern in patterns:
        # Normalize pattern too: strip trailing slash (treat "data/" same as "data")
        pattern = raw_pattern.rstrip("/")
        if not pattern:
            continue

        # 1. Match against the bare filename
        if fnmatch.fnmatch(name, pattern):
            return True

        # 2. Match against the full relative path
        if fnmatch.fnmatch(path, pattern):
            return True

        # 3. Match any path component  →  catches "data" inside "a/data/b/file.csv"
        for part in parts:
            if fnmatch.fnmatch(part, pattern):
                return True

    return False


def get_all_files(local_root: Path, ignore_patterns: list[str]) -> list[Path]:
    """Recursively get all files not matching ignore patterns."""
    files = []
    for root, dirs, filenames in os.walk(local_root):
        # rel_root relative to local_root, normalized (no leading ./)
        rel_root = os.path.relpath(root, local_root)
        if rel_root == ".":
            rel_root = ""

        # Prune ignored dirs in-place so os.walk doesn't descend into them
        dirs[:] = [
            d for d in dirs
            if not should_ignore(os.path.join(rel_root, d) if rel_root else d, ignore_patterns)
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


def sync_files(
    local_root: Path,
    remote_root: str,
    server_config: dict,
    ignore_patterns: list[str],
    changed_files: Optional[list[Path]] = None,
    verbose: bool = True,
) -> tuple[int, int]:
    """
    Sync files from local to remote.

    Args:
        changed_files: If provided, only sync these specific files.
                       If None, sync all files (full sync).

    Returns:
        (synced_count, error_count)
    """
    synced = 0
    errors = 0

    try:
        client = connect_ssh(server_config)
        sftp = client.open_sftp()

        if changed_files is not None:
            files_to_sync = [
                f for f in changed_files
                if not should_ignore(str(f), ignore_patterns)
            ]
        else:
            files_to_sync = get_all_files(local_root, ignore_patterns)

        if not files_to_sync:
            if verbose:
                console.print("[dim]No files to sync.[/dim]")
            sftp.close()
            client.close()
            return 0, 0

        for rel_path in files_to_sync:
            local_file = local_root / rel_path
            remote_file = os.path.join(remote_root, str(rel_path))
            remote_dir = os.path.dirname(remote_file)

            try:
                if remote_dir:
                    ensure_remote_dir(sftp, remote_dir)
                sftp.put(str(local_file), remote_file)
                synced += 1
                if verbose:
                    console.print(f"  [green]✓[/green] {rel_path}")
            except Exception as e:
                errors += 1
                console.print(f"  [red]✗[/red] {rel_path}: {e}")

        sftp.close()
        client.close()

    except Exception as e:
        console.print(f"[red]Connection error:[/red] {e}")
        errors += 1

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