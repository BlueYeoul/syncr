"""Configuration management for syncr."""

import os
import re
import toml
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / ".syncr"
CONFIG_FILE = CONFIG_DIR / "config.toml"
LOCAL_CONFIG_FILE = ".syncr.toml"
IGNORE_FILE = ".syncrignore"

DEFAULT_IGNORE_PATTERNS = [
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".git",
    ".gitignore",
    ".DS_Store",
    "*.egg-info",
    ".venv",
    "venv",
    "node_modules",
    ".syncr.toml",
    ".syncrignore",
    "*.tmp",
    "*.log",
]


# ─── SSH config parser ────────────────────────────────────────────────────────

def parse_ssh_config(host_alias: str) -> Optional[dict]:
    """
    Read ~/.ssh/config and return connection info for a given Host alias.
    Returns None if alias not found.
    """
    ssh_config_path = Path.home() / ".ssh" / "config"
    if not ssh_config_path.exists():
        return None

    result = {}
    in_block = False

    with open(ssh_config_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.lower().startswith("host "):
                current_hosts = line.split(None, 1)[1].split()
                in_block = host_alias in current_hosts
                continue

            if in_block:
                parts = line.split(None, 1)
                if len(parts) == 2:
                    key, value = parts[0].lower(), parts[1].strip()
                    if key == "hostname":
                        result["host"] = value
                    elif key == "user":
                        result["user"] = value
                    elif key == "port":
                        result["port"] = int(value)
                    elif key == "identityfile":
                        result["key_path"] = os.path.expanduser(value)

    if not result:
        return None

    # If no HostName directive, the alias itself is the host
    result.setdefault("host", host_alias)
    result.setdefault("port", 22)
    result.setdefault("auth", "key")
    result.setdefault("key_path", "~/.ssh/id_rsa")
    return result


def is_direct_address(s: str) -> bool:
    """True if the string looks like an IP or FQDN (contains . or :) rather than an SSH alias."""
    return bool(re.search(r'[.:]', s))


# ─── global / local config ────────────────────────────────────────────────────

def get_global_config() -> dict:
    """Load global config (~/.syncr/config.toml)."""
    if not CONFIG_FILE.exists():
        return {"servers": {}}
    return toml.load(CONFIG_FILE)


def save_global_config(config: dict):
    """Save global config."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        toml.dump(config, f)


def get_local_config() -> dict:
    """Load local project config (.syncr.toml)."""
    local = Path(LOCAL_CONFIG_FILE)
    if not local.exists():
        return {}
    return toml.load(local)


def save_local_config(config: dict):
    """Save local project config."""
    with open(LOCAL_CONFIG_FILE, "w") as f:
        toml.dump(config, f)


def get_server_config(profile: str) -> Optional[dict]:
    """Get a specific server profile."""
    global_cfg = get_global_config()
    return global_cfg.get("servers", {}).get(profile)


def list_servers() -> dict:
    """List all saved server profiles."""
    return get_global_config().get("servers", {})


def save_server(profile: str, server_config: dict):
    """Save or update a server profile."""
    global_cfg = get_global_config()
    global_cfg.setdefault("servers", {})[profile] = server_config
    save_global_config(global_cfg)


def delete_server(profile: str) -> bool:
    """Delete a server profile."""
    global_cfg = get_global_config()
    servers = global_cfg.get("servers", {})
    if profile not in servers:
        return False
    del servers[profile]
    save_global_config(global_cfg)
    return True


def get_ignore_patterns() -> list[str]:
    """Get ignore patterns from .syncrignore + defaults."""
    patterns = list(DEFAULT_IGNORE_PATTERNS)
    ignore_file = Path(IGNORE_FILE)
    if ignore_file.exists():
        with open(ignore_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
    return patterns


def init_ignore_file():
    """Create a default .syncrignore file."""
    ignore_file = Path(IGNORE_FILE)
    if ignore_file.exists():
        return False
    with open(ignore_file, "w") as f:
        f.write("# syncr ignore patterns (like .gitignore)\n")
        f.write("# Lines starting with # are comments\n\n")
        f.write("# Python\n")
        f.write("__pycache__\n")
        f.write("*.pyc\n")
        f.write("*.pyo\n")
        f.write(".venv\n")
        f.write("venv\n")
        f.write("*.egg-info\n\n")
        f.write("# Data / models (usually too large)\n")
        f.write("# data/\n")
        f.write("# checkpoints/\n")
        f.write("# *.pt\n")
        f.write("# *.pth\n\n")
        f.write("# System\n")
        f.write(".DS_Store\n")
        f.write("*.tmp\n")
        f.write("*.log\n")
    return True
