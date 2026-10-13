"""
Discovers the Group -> Service hierarchy from disk.

Rules for "is this directory a service root?":
  1. It directly contains at least one file with a recognised log extension.
  2. OR it has an immediate child directory named "log"/"logs" (case-insensitive)
     - the actual files may live further under dated subfolders, e.g.
       Service/Logs/2026-07-17/Service.0.log

Once a directory matches, we stop descending that branch (its whole subtree,
including any dated subfolders, belongs to that one service). If a directory
does not match, we recurse into its children looking for service roots there -
this naturally supports the simple "Group/Service/Logs/*.log" layout from the
spec as well as deeper real-world layouts like "Group/SubGroup/Service/*.log".
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List

from . import config


def _is_log_file(name: str) -> bool:
    ext = os.path.splitext(name)[1].lower()
    return ext in config.LOG_EXTENSIONS


def _has_direct_log_files(dir_path: str) -> bool:
    try:
        with os.scandir(dir_path) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False) and _is_log_file(entry.name):
                    return True
    except OSError:
        pass
    return False


def _has_logs_container_child(dir_path: str) -> bool:
    try:
        with os.scandir(dir_path) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False) and entry.name.lower() in config.LOG_DIR_NAMES:
                    return True
    except OSError:
        pass
    return False


def _prettify(name: str) -> str:
    """Turn a directory/token name into a human friendly label."""
    cleaned = name.replace("_", " ").replace("-", " ").strip()
    # insert spaces before capitals in CamelCase-ish names, but don't mangle acronyms
    out = []
    for i, ch in enumerate(cleaned):
        if ch.isupper() and i > 0 and cleaned[i - 1].islower():
            out.append(" ")
        out.append(ch)
    pretty = "".join(out)
    return " ".join(w[:1].upper() + w[1:] if w and w.islower() else w for w in pretty.split())


@dataclass
class Service:
    key: str          # stable id, e.g. "platform/AdminPanel"
    name: str         # display name, e.g. "Admin Panel"
    group: str        # display group name
    group_key: str
    abs_path: str      # absolute directory on disk (never sent to the frontend)


@dataclass
class DiscoveryResult:
    services: Dict[str, Service] = field(default_factory=dict)          # key -> Service
    groups: Dict[str, List[str]] = field(default_factory=dict)          # group name -> [service keys]

    def to_api(self) -> Dict[str, List[Dict[str, str]]]:
        # `key` is the log-root-relative directory - it's what clients filter
        # by, since display names can repeat across groups.
        return {
            group_name: [{"key": k, "name": self.services[k].name} for k in keys]
            for group_name, keys in self.groups.items()
        }


def _find_service_roots(dir_path: str, depth: int) -> List[str]:
    """Recursively find service-root directories under dir_path."""
    if depth > config.MAX_DISCOVERY_DEPTH:
        return []
    if _has_direct_log_files(dir_path) or _has_logs_container_child(dir_path):
        return [dir_path]

    roots: List[str] = []
    try:
        with os.scandir(dir_path) as it:
            children = sorted((e.name for e in it if e.is_dir(follow_symlinks=False)))
    except OSError:
        return []
    for child in children:
        roots.extend(_find_service_roots(os.path.join(dir_path, child), depth + 1))
    return roots


def discover(root: str = None) -> DiscoveryResult:
    root = root or config.LOG_ROOT
    result = DiscoveryResult()
    if not os.path.isdir(root):
        return result

    with os.scandir(root) as it:
        group_dirs = sorted((e.name for e in it if e.is_dir(follow_symlinks=False)))

    for group_dir in group_dirs:
        group_abs = os.path.join(root, group_dir)
        group_display = _prettify(group_dir)
        service_keys: List[str] = []

        for service_abs in _find_service_roots(group_abs, 1):
            rel = os.path.relpath(service_abs, root).replace(os.sep, "/")
            name_parts = os.path.relpath(service_abs, group_abs).split(os.sep)
            display_name = " / ".join(_prettify(p) for p in name_parts)
            svc = Service(
                key=rel,
                name=display_name,
                group=group_display,
                group_key=group_dir,
                abs_path=service_abs,
            )
            result.services[rel] = svc
            service_keys.append(rel)

        if service_keys:
            result.groups[group_display] = service_keys

    return result


def iter_log_files(service: Service):
    """Yield absolute paths of every log file (recursively) belonging to a service."""
    for dirpath, _dirnames, filenames in os.walk(service.abs_path):
        for fn in filenames:
            if _is_log_file(fn):
                yield os.path.join(dirpath, fn)
