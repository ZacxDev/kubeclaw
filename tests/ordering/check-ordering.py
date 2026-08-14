#!/usr/bin/env python3
"""Pin the startup script's init ORDERING contract.

The container command in templates/deployment.yaml is one ~1,000-line
sequential block, and its ordering is load-bearing in places that are not
obvious from reading any single section. Nothing else in the suite would catch
a re-ordering regression: helm-unittest asserts on rendered text without
regard to sequence, and `make test-shell` executes two blocks in isolation
rather than in the sequence they live in.

This is issue #9's deliverable. It is deliberately NOT a refactor of the
script — it is the guard that has to exist BEFORE anyone attempts one.

Five checks, each closing a different way the guard could pass vacuously:

  PARSE       every `# --- ... ---` marker, INCLUDING the wrapped two-line
              style the script already uses. A parser that only understood the
              single-line form left the wrapped ones invisible, so a new
              section written in the file's own house style was undetectable.

  UNIQUE      duplicate markers are FATAL. Position is a dict keyed by marker
              text, so a duplicate makes it last-wins: a copy of a section
              placed AHEAD of its dependency passes while the hazard is live.

  LEDGER      the SET of markers per values file. Fails when a section is
              added or removed. A new section is not necessarily wrong, but it
              must not slip in without someone deciding where it belongs.

  TERMINAL    the gateway loop is `while true; do openclaw gateway ...; done`
              and never returns, so ANY section after it is dead code. Pinning
              it last constrains all 25 other sections at once — "A precedes
              B" cannot express "B actually runs", so without this a section
              moved past the gateway satisfied every constraint naming it.

  CONSTRAINTS pairwise "A precedes B", each with a reason verified against the
              code. Robust to insertions, unlike pinning the whole sequence.
              Every constraint must be exercised by at least one fixture — an
              unexercised constraint is a declaration, not a check.

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
# either crash or silently check a different tree. realpath, not abspath, so
# invocation through a symlink still resolves to the real chart.
CHART = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

# A marker opens with `# --- ` and closes with ` ---`, possibly on a later line:
#     # --- Skills ---
#     # --- Persist ~/.openclaw on the PVC so sessions, cron state,
#     #     and credentials survive pod restarts ---
OPEN_RE = re.compile(r"^\s*# --- (.*)$")
CLOSE_RE = re.compile(r"^(.*?) ---\s*$")
CONT_RE = re.compile(r"^\s*#\s*(.*)$")

# The revert marker embeds a values-derived string; normalise so the ledger
# does not fail merely because a values file sets a different onRevert mode.
NORMALISE = [
    (re.compile(r"config\.onRevert=\w+"), "config.onRevert=*"),
    (re.compile(r"Bootstrap agent auth from API key \(.*?\)"),
     "Bootstrap agent auth from API key (*)"),
]

# The gateway loop never returns. Anything rendered after it is dead code.
TERMINAL = "Gateway restart loop"

# Markers nested INSIDE another section (the workspace-sync block, itself
# partly a backgrounded subshell inside `while true`). Their position relative
# to each other is not a meaningful init-sequence claim; they are ledgered so
# the set is complete, but they are excluded from the TERMINAL check's
# "distinct init stages" count so it does not overstate coverage.
SUBSECTIONS = {
    "Initial pull: restore workspace from S3",
    "Background sync loop",
    "Upload: find files modified since last sync",
    "Delete reconciliation: every 10 cycles (~2.5 min)",
}

# (must come first, must come after, why) — every reason checked against the
# code, not assumed.
CONSTRAINTS = [
    ("SSH setup", "Repo clone/pull",
     "the clone loop uses SSH remotes (every git.repos[].url in the repo is "
     "git@... form); without /root/.ssh/id_rsa and StrictHostKeyChecking=no "
     "every clone fails host-key verification and set -e crash-loops the pod"),
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
     "the endpoint is started after the skills tree exists; it re-reads the "
     "directory per request, so this pins startup order, not correctness"),
    ("Extra init commands", TERMINAL,
     "user hooks must run before the blocking gateway loop"),
]

# Rendered marker SET per values file. Update with --print when a section is
# legitimately added or removed, and add a CONSTRAINT for the new section.
#
# tests/ordering/values-extra-init.yaml exists so the Extra-init-commands
# constraint is actually exercised — extraInitCommands defaults to "" and no
# examples/ or ci/ file sets it, so that constraint previously ran ZERO times.
# It lives here rather than in ci/ so it does not enter render-diff/byte-diff's
# globs.
COMMON = [
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
    "Persist ~/.openclaw on the PVC so sessions, cron state, and credentials "
    "survive pod restarts",
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
]

LEDGERS = {
    "examples/standard.yaml": COMMON,
    "tests/ordering/values-extra-init.yaml": COMMON + ["Extra init commands"],
    "ci/full-values.yaml": COMMON + [
        "Infrastructure tools",
        "Prune chart-managed skills removed from values",
        "Snapshot restore",
        "Snapshot tools (rclone)",
    ],
}


# A marker must close within this many lines of opening. The script also uses
# the `# --- ` prefix for multi-line explanatory NOTES that never close (see
# the git-sync subshell), so "closes within the window" is what separates a
# section marker from a note. A genuinely unterminated marker is therefore
# skipped here rather than erroring — the LEDGER is the backstop: its section
# vanishes from the set and the run fails.
MAX_MARKER_LINES = 3


def parse_markers(script):
    """Ordered marker titles, handling both the single-line and wrapped styles."""
    lines = script.split("\n")
    out, i = [], 0
    while i < len(lines):
        m = OPEN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        parts, j, title = [], i, None
        rest = m.group(1)
        while j < min(i + MAX_MARKER_LINES, len(lines)):
            closed = CLOSE_RE.match(rest)
            if closed:
                parts.append(closed.group(1).strip())
                title = " ".join(p for p in parts if p)
                break
            parts.append(rest.strip())
            j += 1
            if j >= len(lines):
                break
            cont = CONT_RE.match(lines[j])
            if not cont:
                break
            rest = cont.group(1)
        if title is None:
            i += 1          # an explanatory note, not a section marker
            continue
        for pat, repl in NORMALISE:
            title = pat.sub(repl, title)
        out.append(title)
        i = j + 1
    return out


def markers(values_file):
    out = subprocess.run(
        ["helm", "template", "ord", CHART, "-f", f"{CHART}/{values_file}"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise SystemExit(f"FATAL: helm template failed for {values_file}:\n"
                         f"{out.stderr[-1500:]}")
    for doc in yaml.safe_load_all(out.stdout):
        if isinstance(doc, dict) and doc.get("kind") == "Deployment":
            containers = doc["spec"]["template"]["spec"]["containers"]
            agent = next((c for c in containers if c.get("name") == "agent"), None)
            if agent is None:
                raise SystemExit(
                    f"FATAL: no container named 'agent' in {values_file} "
                    f"(found {[c.get('name') for c in containers]})")
            found = parse_markers(agent["command"][2])
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

    failures, exercised, skipped = [], {i: 0 for i in range(len(CONSTRAINTS))}, False
    for vf, expected in LEDGERS.items():
        found = markers(vf)
        stages = [m for m in found if m not in SUBSECTIONS]
        print(f"== {vf}: {len(found)} markers ({len(stages)} distinct init stages)")

        dupes = {m for m in found if found.count(m) > 1}
        if dupes:
            failures.append(
                f"{vf}: DUPLICATE marker(s) {sorted(dupes)}. Position is keyed "
                f"by marker text, so a duplicate makes ordering last-wins and a "
                f"copy placed ahead of its dependency would pass.")
            skipped = True
            continue

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

        if TERMINAL in found and found[-1] != TERMINAL:
            after = found[found.index(TERMINAL) + 1:]
            failures.append(
                f"{vf}: DEAD CODE — {after} render AFTER {TERMINAL!r}, which "
                f"is `while true; do openclaw gateway ...; done` and never "
                f"returns. Those sections can never execute.")

        pos = {m: i for i, m in enumerate(found)}
        for n, (before, after, why) in enumerate(CONSTRAINTS):
            if before in pos and after in pos:
                exercised[n] += 1
                if pos[before] > pos[after]:
                    failures.append(
                        f"{vf}: ORDER VIOLATION — {before!r} (#{pos[before]}) "
                        f"must precede {after!r} (#{pos[after]}): {why}")

    # A constraint no fixture exercises is a declaration, not a check. This is
    # also what stops the --print workflow from silently deleting coverage:
    # rename a marker, regenerate the ledger, and the constraints naming it go
    # unexercised — which now fails instead of quietly dropping the count.
    # Suppressed when a fixture was skipped above: every constraint would then
    # report "never exercised", burying the real failure under derivative noise.
    for n, count in exercised.items():
        if count == 0 and not skipped:
            b, a, _ = CONSTRAINTS[n]
            failures.append(
                f"CONSTRAINT {b!r} -> {a!r} was never exercised: no fixture "
                f"renders both markers. Either add a fixture that does, or "
                f"remove the constraint — an unexercised one checks nothing.")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    total = sum(exercised.values())
    print(f"\nOK: {len(LEDGERS)} value files, ledgers match, {TERMINAL!r} last, "
          f"{total} constraint checks across {len(CONSTRAINTS)} constraints "
          f"(all exercised)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
