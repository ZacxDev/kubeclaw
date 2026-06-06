#!/usr/bin/env python3
"""Extract a named snippet from the rendered devpod startup script.

helm-unittest only asserts on rendered text; it cannot execute the startup
script. This helper renders the chart with the requested --set overrides,
pulls the container command (`command[2]`, the inline /bin/sh script), and
slices out a contiguous block delimited by anchor substrings so the shell
test harness can run JUST the safety-critical logic (skill prune / config
revert detection) against fixture directories.

Usage:
    extract_block.py --block <name> [--set k=v ...]

Blocks:
    prune   -> the Gap B "Prune chart-managed skills" block, including the
               preceding skill-install loop that builds CURRENT_SKILLS.
    revert  -> the Gap C revert-detection block (pre-doctor hash capture
               through the post-doctor detection), with the actual
               `openclaw doctor` invocation replaced by a no-op so the
               harness can drive doctor behavior via fixtures.
"""
import argparse
import subprocess
import sys

import yaml

# (start_anchor, end_anchor) — first line CONTAINING start through the line
# BEFORE the first line containing end (end exclusive).
BLOCKS = {
    "prune": (
        "# --- Skills ---",
        "# --- Workspace files ---",
    ),
    "revert": (
        "# --- Initialize channels ---",
        "# --- Strip channels not explicitly enabled",
    ),
}


def render_script(sets):
    cmd = ["helm", "template", "test", ".", "--set", "agentName=test"]
    for s in sets:
        cmd += ["--set", s]
    out = subprocess.check_output(cmd, text=True)
    for doc in yaml.safe_load_all(out):
        if doc and doc.get("kind") == "Deployment":
            return doc["spec"]["template"]["spec"]["containers"][0]["command"][2]
    raise SystemExit("no Deployment found in rendered output")


def slice_block(script, start, end):
    lines = script.splitlines()
    si = next((i for i, l in enumerate(lines) if start in l), None)
    if si is None:
        raise SystemExit(f"start anchor not found: {start!r}")
    ei = next((i for i, l in enumerate(lines) if end in l and i > si), None)
    if ei is None:
        raise SystemExit(f"end anchor not found: {end!r}")
    return "\n".join(lines[si:ei])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--block", required=True, choices=list(BLOCKS))
    ap.add_argument("--set", dest="sets", action="append", default=[])
    args = ap.parse_args()
    script = render_script(args.sets)
    start, end = BLOCKS[args.block]
    block = slice_block(script, start, end)
    if args.block == "revert":
        # Replace the real doctor call with a placeholder the harness controls.
        block = block.replace(
            'openclaw doctor --fix || echo "Doctor exited with $?, continuing..."',
            ': "${DOCTOR_HOOK:?DOCTOR_HOOK must be set}"; eval "$DOCTOR_HOOK"',
        )
    sys.stdout.write(block + "\n")


if __name__ == "__main__":
    main()
