#!/usr/bin/env python3
"""Semantic render diff for the generated openclaw.json.

Unit assertions on rendered TEXT cannot catch a refactor that changes the
generated config's meaning. This renders the chart against every value file in
the repo, extracts data["openclaw.json"] from the agent ConfigMap, parses it,
and deep-compares two captures.

Usage:
    render-diff.py capture <outdir>        render every value file, save parsed JSON
    render-diff.py compare <dirA> <dirB>   deep-compare two captures
    render-diff.py selftest                NEGATIVE CONTROL - prove compare can fail

Read selftest first. A comparator that always reports "identical" is the
default failure mode of this kind of tool, so `compare` refuses to run until
`selftest` has demonstrated it can detect a one-nested-key difference.

Requires: helm, python3 + PyYAML.
"""
import json
import os
import subprocess
import sys

import yaml

CHART = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def value_files():
    """Every value file in the repo, as (label, path)."""
    out = []
    for d in ("examples", "examples/fleet", "ci"):
        full = os.path.join(CHART, d)
        if not os.path.isdir(full):
            continue
        for f in sorted(os.listdir(full)):
            if not f.endswith(".yaml"):
                continue
            label = f"{d.replace('/', '_')}_{f[:-5]}"
            out.append((label, os.path.join(full, f)))
    return out


def render_config(path):
    """Render the chart with `path` and return the parsed openclaw.json.

    Returns None if the chart renders but emits no agent ConfigMap.
    Raises on a render failure - a value file that no longer renders is a
    finding, not something to skip silently.
    """
    proc = subprocess.run(
        ["helm", "template", "difftest", CHART, "-f", path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"helm template failed for {path}:\n{proc.stderr[-2000:]}")

    for doc in yaml.safe_load_all(proc.stdout):
        if not doc or doc.get("kind") != "ConfigMap":
            continue
        data = doc.get("data") or {}
        if "openclaw.json" in data:
            return json.loads(data["openclaw.json"])
    return None


def cmd_capture(outdir):
    os.makedirs(outdir, exist_ok=True)
    n = 0
    for label, path in value_files():
        cfg = render_config(path)
        if cfg is None:
            print(f"  !! {label}: rendered no openclaw.json")
            continue
        with open(os.path.join(outdir, label + ".json"), "w") as fh:
            json.dump(cfg, fh, indent=2, sort_keys=True)
        n += 1
        print(f"  ok {label}")
    if n == 0:
        # A capture of zero files would make `compare` trivially pass.
        print("FATAL: captured 0 configs - nothing to compare", file=sys.stderr)
        sys.exit(2)
    print(f"captured {n} configs -> {outdir}")


def diff_paths(a, b, path="$"):
    """Yield human-readable differences between two parsed JSON values."""
    if type(a) is not type(b):
        yield f"{path}: type {type(a).__name__} != {type(b).__name__}"
        return
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                yield f"{path}.{k}: only in B ({b[k]!r})"
            elif k not in b:
                yield f"{path}.{k}: only in A ({a[k]!r})"
            else:
                yield from diff_paths(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        if len(a) != len(b):
            yield f"{path}: length {len(a)} != {len(b)}"
            return
        for i, (x, y) in enumerate(zip(a, b)):
            yield from diff_paths(x, y, f"{path}[{i}]")
    elif a != b:
        yield f"{path}: {a!r} != {b!r}"


def stamp_path():
    """Stamp keyed to THIS script's content.

    A bare `.selftest-passed` file is a permanent one-time unlock: edit the
    comparator afterwards and `compare` keeps running against a stamp earned
    by the old code. Hashing the script means any edit invalidates the unlock.
    """
    import hashlib
    h = hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:16]
    return os.path.join(CHART, f".selftest-passed-{h}")


def cmd_selftest():
    """Negative control: prove diff_paths reports a real difference.

    Without this, a `compare` that prints "identical" is indistinguishable
    from a comparator wired to nothing.
    """
    a = {"agents": {"defaults": {"model": {"primary": "x"}, "maxConcurrent": 4}}}
    b = {"agents": {"defaults": {"model": {"primary": "y"}, "maxConcurrent": 4}}}
    diffs = list(diff_paths(a, b))
    if len(diffs) != 1 or "primary" not in diffs[0]:
        print(f"FAIL: expected exactly 1 diff on .primary, got {diffs}", file=sys.stderr)
        sys.exit(1)
    print(f"  ok detects nested value change: {diffs[0]}")

    # Also prove it catches a missing key and a changed list length.
    if not list(diff_paths({"a": 1}, {})):
        print("FAIL: missing-key difference not detected", file=sys.stderr)
        sys.exit(1)
    print("  ok detects missing key")
    if not list(diff_paths({"a": [1, 2]}, {"a": [1]})):
        print("FAIL: list-length difference not detected", file=sys.stderr)
        sys.exit(1)
    print("  ok detects list length change")

    # Positive control: identical inputs must produce zero diffs.
    if list(diff_paths(a, a)):
        print("FAIL: identical inputs reported as different", file=sys.stderr)
        sys.exit(1)
    print("  ok identical inputs -> 0 diffs")

    # POSITIVE CONTROL ON THE EXTRACTION PATH, not just the comparator.
    # diff_paths is a pure function; proving it works says nothing about
    # whether render_config actually observes the config. A render_config
    # stubbed to a constant would yield "N/N identical" with every check
    # above still passing. So render a real value file and assert we can
    # both SEE a known key and DETECT a change to it.
    probe = os.path.join(CHART, "examples", "standard.yaml")
    if os.path.exists(probe):
        cfg = render_config(probe)
        if not cfg:
            print("FAIL: render_config returned nothing for examples/standard.yaml",
                  file=sys.stderr)
            sys.exit(1)
        try:
            model = cfg["agents"]["defaults"]["model"]["primary"]
        except (KeyError, TypeError):
            print(f"FAIL: extraction produced no agents.defaults.model.primary: "
                  f"{list(cfg)[:8]}", file=sys.stderr)
            sys.exit(1)
        mutated = json.loads(json.dumps(cfg))
        mutated["agents"]["defaults"]["model"]["primary"] = model + "-MUTANT"
        if not list(diff_paths(cfg, mutated)):
            print("FAIL: end-to-end control - real config vs mutated compared equal",
                  file=sys.stderr)
            sys.exit(1)
        print(f"  ok end-to-end: extracted model.primary={model!r} and detected a change to it")
    else:
        # HARD FAIL, not a skip. This is the only control that exercises
        # render_config/extraction; skipping it while still writing the stamp
        # would unlock `compare` with the exact blind spot this check exists
        # to close. Matches cmd_capture's and byte-diff's FATAL-on-zero
        # posture rather than degrading quietly.
        print("FAIL: examples/standard.yaml missing - cannot run the end-to-end "
              "control, refusing to unlock compare", file=sys.stderr)
        sys.exit(1)

    open(stamp_path(), "w").close()
    print(f"SELFTEST PASSED - compare unlocked for this script version")


def cmd_compare(da, db):
    if not os.path.exists(stamp_path()):
        print("REFUSING: run `render-diff.py selftest` first (negative control).\n"
              "  (The stamp is keyed to this script's hash, so editing the script "
              "re-locks compare until selftest passes again.)",
              file=sys.stderr)
        sys.exit(2)

    fa = {f for f in os.listdir(da) if f.endswith(".json")}
    fb = {f for f in os.listdir(db) if f.endswith(".json")}
    if not fa:
        print("FATAL: capture A is empty", file=sys.stderr)
        sys.exit(2)

    # Split the set mismatch BY DIRECTION rather than failing on any difference.
    #
    # removed (in the ref, gone in the working tree) stays FATAL: a value file
    # that vanished from the sweep silently shrinks coverage, which is exactly
    # what this guard exists to catch.
    #
    # added (new in the working tree) is informational: a genuinely new value
    # file has no counterpart on an older ref, so failing here would make CI
    # red on every PR that adds one — a known false-red, which trains people
    # to merge through the gate.
    removed = fa - fb
    added = fb - fa
    if removed:
        print(f"FATAL: value files present in A but missing from B: "
              f"{sorted(removed)}", file=sys.stderr)
        sys.exit(2)
    for f in sorted(added):
        print(f"  NEW  {f} (no counterpart in A - not compared)")

    common = fa & fb
    if not common:
        print("FATAL: no value files in common to compare", file=sys.stderr)
        sys.exit(2)

    failed = 0
    for f in sorted(common):
        a = json.load(open(os.path.join(da, f)))
        b = json.load(open(os.path.join(db, f)))
        diffs = list(diff_paths(a, b))
        if diffs:
            failed += 1
            print(f"  DIFF {f}")
            for d in diffs[:20]:
                print(f"        {d}")
        else:
            print(f"  same {f}")
    # Count over `common`, not `fa` — with added files present, len(fa) would
    # understate the denominator and print a misleading ratio.
    print(f"\n{len(common) - failed}/{len(common)} identical"
          + (f" ({len(added)} new, not compared)" if added else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "capture":
        cmd_capture(sys.argv[2])
    elif cmd == "compare":
        cmd_compare(sys.argv[2], sys.argv[3])
    elif cmd == "selftest":
        cmd_selftest()
    else:
        print(__doc__)
        sys.exit(2)
