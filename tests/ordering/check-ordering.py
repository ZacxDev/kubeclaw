#!/usr/bin/env python3
"""Pin the startup script's init ORDERING contract.

The container command in templates/deployment.yaml is one ~1,000-line
sequential block, and its ordering is load-bearing in places that are not
obvious from reading any single section. Nothing else in the suite would catch
a re-ordering regression: helm-unittest asserts on rendered text without
regard to sequence, and `make test-shell` executes two blocks in isolation
rather than the sequence they live in.

This is issue #9's deliverable. It is deliberately NOT a refactor of the
script — it is the guard that has to exist BEFORE anyone attempts one.

Two independent checks, because they fail on different things:

  LEDGER      the SET of section markers rendered for a given values file.
              Fails when a section is added or removed. A new section is not
              necessarily wrong, but it must not slip in without someone
              deciding where it belongs — so the failure says "declare a
              constraint or update the ledger".

  CONSTRAINTS pairwise "A must precede B", each with a reason verified against
              the code. Fails when a section MOVES. Robust to insertions,
              unlike pinning the full sequence, so it does not fire on benign
              additions.

Checked against several values files so a constraint is not confirmed by a
single feature combination.

Usage:
    check-ordering.py            # verify
    check-ordering.py --print    # print current markers, to update LEDGERS
"""
import os
import re
import subprocess
import sys

import yaml

# Derived from THIS file's location (tests/ordering/ -> chart root), not from
# `git rev-parse --show-toplevel`. The git form breaks outside a repo and, worse,
# resolves to the enclosing repo root rather than the chart this script ships
# with — so a copy of the chart (a byte-diff tar extract, a vendored copy) would
# either crash or silently check a different tree. Matches scripts/render-diff.py.
CHART = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MARKER_RE = re.compile(r"^\s*# --- (.+?) ---\s*$", re.M)

# The revert marker embeds a values-derived string; normalise so the ledger
# does not fail merely because a values file sets a different onRevert mode.
NORMALISE = [(re.compile(r"config\.onRevert=\w+"), "config.onRevert=*")]

# (must come first, must come after, why) — every reason checked against the
# code, not assumed.
CONSTRAINTS = [
    ("Repo clone/pull", "Background git auto-pull loop",
     "the loop fetches repos that the clone step must have created"),
    ("Snapshot tools (rclone)", "Snapshot restore",
     "restore invokes rclone, which the tools step installs"),
    ("Snapshot restore", "Skills",
     "CRITICAL: rclone sync during restore deletes files absent from the "
     "snapshot, so ConfigMap skills must be written AFTER it"),
    ("Snapshot restore", "Workspace files",
     "same rclone-sync deletion hazard as Skills"),
    ("Snapshot restore", "Workspace content (inline)",
     "same rclone-sync deletion hazard as Skills"),
    ("Skills", "Prune chart-managed skills removed from values",
     "prune matches against CURRENT_SKILLS, which the install loop builds"),
    ("OAuth credentials", "Bootstrap agent auth from Claude credentials",
     "bootstrap reads /root/.claude/.credentials.json, which this step "
     "populates and symlinks onto the PVC"),
    ("Generate openclaw.json with secrets injected", "Initialize channels",
     "`openclaw doctor --fix` runs against the generated config"),
    ("Initialize channels", "Detect silent config revert (config.onRevert=*)",
     "detection compares the POST-doctor config against the chart's intent"),
    ("Detect silent config revert (config.onRevert=*)",
     "Strip channels not explicitly enabled in helm values",
     "the strip legitimately rewrites openclaw.json, so detection must read "
     "the file first or it cannot tell a revert from a strip"),
    ("Skills", "Skills API endpoint (port 18790)",
     "the API serves skills from the tree the install loop writes"),
    ("Skills API endpoint (port 18790)", "Gateway restart loop",
     "the gateway loop blocks, so anything after it never runs"),
    ("Extra init commands", "Gateway restart loop",
     "user hooks must run before the blocking gateway loop"),
]

# Rendered marker SET per values file. Update with --print when a section is
# legitimately added or removed, and add a CONSTRAINT for the new section.
LEDGERS = {
    "examples/standard.yaml": [
        "Background git auto-pull loop",
        "Background sync loop",
        "Bootstrap agent auth from Claude credentials",
        "Delete reconciliation: every 10 cycles (~2.5 min)",
        "Detect silent config revert (config.onRevert=*)",
        "Email plugin",
        "Gateway restart loop",
        "Generate openclaw.json with secrets injected",
        "Initial pull: restore workspace from S3",
        "Initialize channels",
        "OAuth credentials",
        "Persist WhatsApp Baileys credentials across restarts",
        "Pre-approve Telegram users",
        "Repo clone/pull",
        "SSH setup",
        "Skills",
        "Skills API endpoint (port 18790)",
        "Strip channels not explicitly enabled in helm values",
        "Upload: find files modified since last sync",
        "Workspace content (inline)",
        "Workspace files",
        "Workspace sync (2-way, background)",
    ],
    "ci/full-values.yaml": [
        "Background git auto-pull loop",
        "Background sync loop",
        "Bootstrap agent auth from Claude credentials",
        "Delete reconciliation: every 10 cycles (~2.5 min)",
        "Detect silent config revert (config.onRevert=*)",
        "Email plugin",
        "Gateway restart loop",
        "Generate openclaw.json with secrets injected",
        "Infrastructure tools",
        "Initial pull: restore workspace from S3",
        "Initialize channels",
        "OAuth credentials",
        "Persist WhatsApp Baileys credentials across restarts",
        "Pre-approve Telegram users",
        "Prune chart-managed skills removed from values",
        "Repo clone/pull",
        "SSH setup",
        "Skills",
        "Skills API endpoint (port 18790)",
        "Snapshot restore",
        "Snapshot tools (rclone)",
        "Strip channels not explicitly enabled in helm values",
        "Upload: find files modified since last sync",
        "Workspace content (inline)",
        "Workspace files",
        "Workspace sync (2-way, background)",
    ],
}


def markers(values_file):
    """Ordered section markers from the rendered container command."""
    out = subprocess.run(
        ["helm", "template", "ord", CHART, "-f", f"{CHART}/{values_file}"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise SystemExit(f"FATAL: helm template failed for {values_file}:\n"
                         f"{out.stderr[-1500:]}")
    for doc in yaml.safe_load_all(out.stdout):
        if isinstance(doc, dict) and doc.get("kind") == "Deployment":
            script = doc["spec"]["template"]["spec"]["containers"][0]["command"][2]
            found = MARKER_RE.findall(script)
            for pat, repl in NORMALISE:
                found = [pat.sub(repl, m) for m in found]
            if not found:
                raise SystemExit(
                    f"FATAL: no section markers found in {values_file}. The "
                    "marker format or the extraction path changed — this check "
                    "is testing nothing until that is fixed.")
            return found
    raise SystemExit(f"FATAL: no Deployment rendered for {values_file}")


def main():
    if "--print" in sys.argv:
        for vf in LEDGERS:
            print(f'    "{vf}": [')
            for m in sorted(set(markers(vf))):
                print(f'        "{m}",')
            print("    ],")
        return 0

    failures = []
    for vf, expected in LEDGERS.items():
        found = markers(vf)
        print(f"== {vf}: {len(found)} markers")

        got, want = set(found), set(expected)
        for extra in sorted(got - want):
            failures.append(
                f"{vf}: NEW section {extra!r} is not in the ledger. Decide "
                f"where it belongs: add a CONSTRAINT pinning its position, "
                f"then update LEDGERS (--print).")
        for gone in sorted(want - got):
            failures.append(
                f"{vf}: section {gone!r} disappeared from the render. If that "
                f"is intended, remove it from LEDGERS and drop any CONSTRAINT "
                f"naming it.")

        pos = {m: i for i, m in enumerate(found)}
        for before, after, why in CONSTRAINTS:
            if before in pos and after in pos and pos[before] > pos[after]:
                failures.append(
                    f"{vf}: ORDER VIOLATION — {before!r} (#{pos[before]}) must "
                    f"precede {after!r} (#{pos[after]}): {why}")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    checked = sum(
        1 for vf in LEDGERS
        for b, a, _ in CONSTRAINTS
        if b in set(LEDGERS[vf]) and a in set(LEDGERS[vf])
    )
    print(f"\nOK: {len(LEDGERS)} value files, ledgers match, "
          f"{checked} constraint checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
