#!/usr/bin/env python3
"""Manage one bundled FIA patch using only the Python standard library."""

import argparse
import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def transform(original, patch, target):
    """Apply a single-file unified diff exactly; no fuzz or offset matching."""
    lines = patch.decode("utf-8").splitlines(keepends=True)
    if lines[:2] != [f"--- a/{target}\n", f"+++ b/{target}\n"]:
        raise ValueError("Patch must target exactly the manifest file")
    source = original.decode("utf-8").splitlines(keepends=True)
    output = []
    cursor = 0
    index = 2
    hunks = 0
    while index < len(lines):
        match = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n", lines[index])
        if not match:
            raise ValueError("Invalid unified diff hunk")
        old_start, old_count, new_start, new_count = match.groups()
        old_count = int(old_count or 1)
        new_count = int(new_count or 1)
        start = int(old_start) - (1 if old_count else 0)
        if start < cursor or start > len(source):
            raise ValueError("Invalid hunk position")
        output.extend(source[cursor:start])
        cursor = start
        expected_new_start = int(new_start) - (1 if new_count else 0)
        if len(output) != expected_new_start:
            raise ValueError("Invalid output hunk position")
        index += 1
        old_seen = new_seen = 0
        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if line[:1] not in (" ", "+", "-"):
                raise ValueError("Unsupported diff record")
            if line[0] in " -":
                if cursor >= len(source) or source[cursor] != line[1:]:
                    raise ValueError("Patch context does not match exactly")
                cursor += 1
                old_seen += 1
            if line[0] in " +":
                output.append(line[1:])
                new_seen += 1
            index += 1
        if (old_seen, new_seen) != (old_count, new_count):
            raise ValueError("Invalid hunk line counts")
        hunks += 1
    if not hunks:
        raise ValueError("Empty patch")
    output.extend(source[cursor:])
    result = "".join(output).encode("utf-8")
    ast.parse(result.decode("utf-8"), filename=target)
    return result


def atomic_write(path, data, mode):
    fd, name = tempfile.mkstemp(prefix=".fia-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def classify(digest, manifest):
    if digest == manifest["original_sha256"]:
        return "original"
    if digest == manifest["patched_sha256"]:
        return "applied"
    if digest in manifest["known_variants"]:
        return "other-variant"
    return "unknown-modification"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "apply", "restore"))
    parser.add_argument("--source-root", type=Path, default=Path("/vllm-workspace/vllm-ascend"))
    args = parser.parse_args()
    skill = Path(__file__).resolve().parents[1]
    manifest = json.loads((skill / "assets/baseline.json").read_text())
    root = args.source_root.resolve(strict=True)
    target = root / manifest["target"]
    if target.is_symlink() or not target.resolve(strict=True).is_relative_to(root):
        raise ValueError("Source must be a regular file inside --source-root")
    if not target.is_file():
        raise ValueError("Source is not a regular file")
    current = target.read_bytes()
    digest = sha(current)
    state = classify(digest, manifest)
    if args.action == "status":
        print(json.dumps({"state": state, "sha256": digest, "target": str(target),
                          "layout": manifest["known_variants"].get(digest)}, ensure_ascii=False))
        return
    if state in ("other-variant", "unknown-modification"):
        raise ValueError(f"Refusing {args.action}: {state}, SHA-256={digest}. "
                         "Restore the active skill first; preserve and inspect unknown changes.")
    if (args.action == "apply" and state == "applied") or (args.action == "restore" and state == "original"):
        print("Already applied; no changes." if state == "applied" else "Already original; no changes.")
        return
    state_dir = root / ".fia-layout-patches"
    if state_dir.is_symlink():
        raise ValueError("State directory must not be a symlink")
    state_dir.mkdir(mode=0o700, exist_ok=True)
    lock_path = state_dir / "lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.read_bytes() != current:
            raise ValueError("Source changed concurrently; retry status")
        patch = (skill / "assets/layout.patch").read_bytes()
        if sha(patch) != manifest["patch_sha256"]:
            raise ValueError("Bundled patch checksum mismatch")
        backup = state_dir / (manifest["original_sha256"] + ".original")
        if backup.is_symlink():
            raise ValueError("Backup must not be a symlink")
        if args.action == "apply":
            result = transform(current, patch, manifest["target"])
            if sha(result) != manifest["patched_sha256"]:
                raise ValueError("Patched source checksum mismatch")
            if backup.exists():
                if sha(backup.read_bytes()) != manifest["original_sha256"]:
                    raise ValueError("Existing backup is corrupt; refusing to replace it")
            else:
                atomic_write(backup, current, 0o600)
        else:
            if not backup.is_file():
                raise ValueError("Original backup is missing; refusing restore")
            result = backup.read_bytes()
            if sha(result) != manifest["original_sha256"]:
                raise ValueError("Original backup checksum mismatch")
            if transform(result, patch, manifest["target"]) != current:
                raise ValueError("Backup and patch do not reproduce current source")
        if target.read_bytes() != current:
            raise ValueError("Source changed concurrently; refusing overwrite")
        mode = stat.S_IMODE(target.stat().st_mode)
        atomic_write(target, result, mode)
        if target.read_bytes() != result:
            raise ValueError("Post-write verification failed")
        print(f"{args.action}: OK ({manifest['layout']}); SHA-256={sha(result)}")
        print("Restart the affected process to load the source. Performance and accuracy are not validated.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"ERROR: {exc}")
