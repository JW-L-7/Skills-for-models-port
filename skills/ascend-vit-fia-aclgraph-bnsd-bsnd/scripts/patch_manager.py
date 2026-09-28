#!/usr/bin/env python3
"""Manage a bundled two-file FIA graph patch using only the Python standard library."""

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "apply", "restore"))
    parser.add_argument("--source-root", type=Path, default=Path("/vllm-workspace/vllm-ascend"))
    args = parser.parse_args()
    skill = Path(__file__).resolve().parents[1]
    manifest = json.loads((skill / "assets/baseline.json").read_text())
    root = args.source_root.resolve(strict=True)
    items = []
    for entry in manifest["files"]:
        path = root / entry["target"]
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root) or not path.is_file():
            raise ValueError(f"Source must be a regular file within the root: {path}")
        data = path.read_bytes()
        digest = sha(data)
        state = ("original" if digest == entry["original_sha256"] else
                 "applied" if digest == entry["patched_sha256"] else
                 "other-variant" if digest in entry["known_variants"] else "unknown-modification")
        items.append(dict(entry=entry, path=path, data=data, state=state, sha256=digest))
    states = {item["state"] for item in items}
    overall = next(iter(states)) if len(states) == 1 else "mixed"
    if states == {"original", "applied"}:
        overall = "partial-current-variant"
    report = {"state": overall, "skill": manifest["skill"], "files": [
        {"target": str(i["path"]), "state": i["state"], "sha256": i["sha256"]} for i in items]}
    if args.action == "status":
        print(json.dumps(report, ensure_ascii=False))
        return
    if states - {"original", "applied"}:
        raise ValueError(f"Refusing {args.action}: {json.dumps(report)}. "
                         "Restore the active skill first; inspect unknown changes without overwriting them.")
    if args.action == "apply" and overall == "partial-current-variant":
        raise ValueError("Partial operation detected. Run this skill's restore before applying again.")
    if (args.action == "apply" and overall == "applied") or (args.action == "restore" and overall == "original"):
        print("Already applied; no changes." if overall == "applied" else "Already original; no changes.")
        return
    state_dir = root / ".fia-layout-patches"
    if state_dir.is_symlink():
        raise ValueError("State directory must not be a symlink")
    state_dir.mkdir(mode=0o700, exist_ok=True)
    lock_fd = os.open(state_dir / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Validate every source, patch and backup before changing either source file.
        for item in items:
            entry, path, current = item["entry"], item["path"], item["data"]
            if path.read_bytes() != current:
                raise ValueError("Source changed concurrently; retry status")
            patch = (skill / entry["patch"]).read_bytes()
            if sha(patch) != entry["patch_sha256"]:
                raise ValueError(f"Bundled patch checksum mismatch: {entry['patch']}")
            backup = state_dir / (entry["original_sha256"] + ".original")
            if backup.is_symlink():
                raise ValueError("Backup must not be a symlink")
            base = current if item["state"] == "original" else backup.read_bytes()
            if sha(base) != entry["original_sha256"]:
                raise ValueError(f"Original backup checksum mismatch: {backup}")
            patched = transform(base, patch, entry["target"])
            if sha(patched) != entry["patched_sha256"]:
                raise ValueError("Patched source checksum mismatch")
            if item["state"] == "applied" and current != patched:
                raise ValueError("Backup and patch do not reproduce current source")
            if backup.exists() and sha(backup.read_bytes()) != entry["original_sha256"]:
                raise ValueError("Existing backup is corrupt; refusing to overwrite it")
            item.update(backup=backup, base=base, result=patched if args.action == "apply" else base,
                        mode=stat.S_IMODE(path.stat().st_mode))
        for item in items:
            if not item["backup"].exists():
                atomic_write(item["backup"], item["base"], 0o600)
        written = []
        try:
            for item in items:
                if item["path"].read_bytes() != item["data"]:
                    raise ValueError("Source changed concurrently; refusing overwrite")
                if item["result"] == item["data"]:
                    continue
                atomic_write(item["path"], item["result"], item["mode"])
                written.append(item)
                if item["path"].read_bytes() != item["result"]:
                    raise ValueError("Post-write verification failed")
        except BaseException:
            # Best-effort rollback on ordinary failure. A killed process may leave
            # a partial state; restore accepts only original / this-patch hashes.
            for item in reversed(written):
                if item["path"].read_bytes() == item["result"]:
                    atomic_write(item["path"], item["data"], item["mode"])
            raise
        for item in items:
            print(f"{args.action}: OK {item['entry']['target']} SHA-256={sha(item['result'])}")
        print("Restart the service and recapture encoder graphs. Performance and accuracy are not validated.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"ERROR: {exc}")
