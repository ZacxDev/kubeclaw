# Handoff: kubeclaw-0.8.0 — 2026-08-14

## Run this first — the index, one read-only command
```bash
python3 ~/workspace/devrc/scripts/lib/subsystem_recall.py --repo /home/zach/workspace/kubeclaw
```
Terse pointers this doc does not carry, curated by past sessions and outliving it.
🔴 RECALL, NOT LIVE OBSERVATION — every line is a pointer to VERIFY, never a current
reading, and it may describe a gotcha already fixed. `scope-absent`/`scope-empty` means
nothing is recorded yet: ordinary, not an error, and not a clean bill of health.
Non-blocking: if it exits non-zero, print the stderr line and carry on.

## Goal

Refresh kubeclaw's docs against reality, reposition it for platform engineers, then close
the composability gap that repositioning exposed — and build the verification apparatus
that makes those claims checkable rather than asserted.

## State now

- **Branch:** `trunk` @ `d350125`, clean, in sync with origin. Chart **0.8.0**.
- **CI:** live and green. `.github/workflows/verify.yml` runs four tiers on every PR and
  push. Record: **1 red, 5 green** — the instrument has been observed failing, not just
  passing.

### DONE this session (7 PRs merged in kubeclaw)

| PR | Commit | What |
|----|--------|------|
| #5 | `a5e54e8` | Docs refreshed 0.3.6→0.7.1 reality; repositioned as "composable Kubernetes control plane"; `examples/fleet/` (3 agents, 3 RBAC tiers) |
| #6 | `6f60dae` | `.gitignore` for local artifacts; deleted a misplaced 116 MB `tailwindcss-linux-x64` |
| #10 | `c755265` | `claudedocs/composability-gaps.md` + issues #7–#9 |
| #11 | `c4eac39` | **`configOverlay`** (additive deep-merge onto generated `openclaw.json`) + `scripts/render-diff.py` + `make byte-diff` |
| #14 | `d71034f` | CI: all four tiers on every PR |
| #15 | `32fb10a` | `ci/overlay-values.yaml` — makes the diff gates cover the *merge* (closes #13) |
| #16 | `d350125` | `tests/ordering/check-ordering.py` — pins init ordering (closes #9) |

Plus **homelab-infra #322** (`44f40134`): vendored kubeclaw chart re-synced 0.7.1 → **0.8.0**,
and `containers/clawgate/Makefile`'s `sync-chart` exclude list hardened.

### The four verification tiers (all wired into CI)

```bash
make test          # 189 helm-unittest tests, 19 suites
make test-shell    # 16 checks: executes the rendered startup script under sh
make test-ordering # init ordering contract: 4 fixtures, 13 constraints, 6 self-tested guards
make render-diff   # semantic diff of generated openclaw.json vs a ref (11/11)
make byte-diff     # full-manifest byte diff, chart version normalised (11 compared)
```

### Deploy status — be precise

- kubeclaw is a **chart**; nothing is "deployed" by merging. Consumers pick it up via Flux.
- **clawgate is NOT running 0.8.0.** It runs a pinned image
  `harbor.homelab.lan/library/clawgate:0.7.94` (`clusters/workbench/apps/clawgate/deployment.yaml:84`)
  and the chart is `//go:embed`-ed into the binary. The vendored 0.8.0 chart takes effect
  **only on the next image build + tag bump** — that step was deliberately left undone
  because it *is* a live deploy.

## Open investigations — live diagnosis state

### #12 — `matrix.enabled: true` + null `typingIndicator` renders invalid JSON

Not a mystery; fully diagnosed, deliberately not fixed (kept out of #11's scope so the
audit stayed valid). Captured so nobody re-derives it.

- **Symptom + exact repro:**
  ```bash
  helm template t . -f examples/standard.yaml \
    --set channels.matrix.enabled=true --set channels.matrix.typingIndicator=null
  ```
  Renders successfully (exit 0) and emits **invalid JSON** into the ConfigMap.
- **Observed (with values):** the matrix block in `templates/configmap.yaml` emits
  `"autoJoin": "always",` then closes the object because `typingIndicator` is falsy,
  leaving a trailing comma. On the `configOverlay` path this is caught at render time:
  `error calling mustFromJson: invalid character '}' looking for beginning of object key string`.
  On the default (verbatim) path it ships.
- **Ruled out:** not introduced by #11 — reproduced on `trunk` before that PR. Not a
  values-schema issue; `typingIndicator` has a default, so it requires explicitly nulling it.
- **Leading hypothesis:** conditional-comma placement bug, same shape already solved
  correctly for `whatsapp.allowFrom` / `teams` / `sms` / `email` in the same file.
- **Impact is bounded:** `channels.matrix.enabled` defaults `false`, and at boot the
  startup script's `jq` fails loudly on the invalid JSON rather than running a wrong config.
- 🔴 **Coupling — read before fixing:** `tests/configmap_test.yaml`'s
  *"a malformed generated config fails the render on the overlay path"* test **uses this bug
  as its fixture**. Fixing #12 turns that test red. It needs a replacement way to generate
  malformed JSON in the same PR.
- **Next probe:** none needed — go straight to the fix. Move the comma to emit with the
  preceding key, then add a unit test asserting the rendered `openclaw.json` **parses**
  across a matrix of channel combinations (the current suite only regex-matches fragments,
  so no test would catch a structurally invalid document).

## Next steps (ranked)

1. **Nothing is required.** Everything shipped is verified and green; this is a clean stop.
2. **#12** (small, real, has the fixture coupling above). Best pick if you want one more.
3. **clawgate image rebuild + tag bump** — the only way the vendored 0.8.0 chart reaches a
   running agent. This is a live deploy to the workbench cluster; ride it with the next
   clawgate release rather than alone.
4. **#8** (workflow executor indirection) — argued down twice as lowest leverage; nothing
   is blocked by it. Don't reverse without a reason.
5. `.helmignore` doesn't exclude `tests/`, `scripts/`, `ci/`, `.github/` — so they ship
   inside `helm package` output. Cosmetic only (Flux consumes the chart as a GitRepository,
   never packaged), pre-existing, and noted by two audits.

## Gotchas / decisions / dead-ends

**Verification traps hit this session — each cost a round to find:**

- 🔴 **`fromJson` does NOT fail on malformed input.** It returns `{"Error": "<msg>"}` and the
  render *succeeds*, silently replacing the whole config with an error map. Because that map
  is valid JSON, the startup script's `jq` passes and the agent boots with no model, no
  workspace, no channels. Use **`mustFromJson`** (`templates/configmap.yaml`).
- 🔴 **`checksum/config` hashes the whole rendered `configmap.yaml`, which carries the
  `helm.sh/chart: kubeclaw-<version>` label.** So *any* version bump rolls every pod. Also:
  a stray leading newline from a `define` moves it — which is why `{{- end -}}`'s trailing
  dash is load-bearing and commented as such.
- 🔴 **`render-diff` and `byte-diff` catch different things.** Dropping that `{{- end -}}`
  dash leaves render-diff at 10/10 identical while the checksum moves. Run **both** for any
  change to config generation.
- 🔴 **`make` defaults to `/bin/sh`** — bash on NixOS, dash on Ubuntu. `set -o pipefail` in a
  recipe passes locally and fails in CI. Fixed via `SHELL := $(shell command -v bash)`;
  resolved, not hardcoded, because **`/bin/bash` does not exist on NixOS**.
- 🔴 **A measurement taken before your last change is not a measurement.** The "byte-identical,
  restarts nothing" claim in #11 was measured *before* the `Chart.yaml` bump and was false.
- 🔴 **Mutation harness false kills.** The ordering check originally resolved its chart root
  via `git rev-parse --show-toplevel`; in `cp -a` scratch copies (no `.git`) it *crashed*, and
  four "KILLED" results were really four crashes. Always run an **unmutated copy in the same
  environment** as the control. Derive roots from `__file__` (both `scripts/render-diff.py`
  and `tests/ordering/check-ordering.py` now do).
- **An auditor's finding is a claim too.** One audit reported an off-by-one in
  `found[found.index(TERMINAL) + 1:]`; it was wrong (`[A,T,B,C]` → `[B,C]`). Verified before
  "fixing" it.

**clawgate vendoring (homelab-infra):**

- `sync-chart`'s rsync has **no trailing `--exclude '*'`**, so `--include` lines rescue
  nothing and anything unexcluded IS copied. Combined with `//go:embed all:` (the `all:`
  prefix includes dot-paths), a naive re-sync would have baked `.github/workflows/verify.yml`
  and `scripts/` into the clawgate binary. Excludes added.
- **rsync does not honour `.gitignore`** — `.opencode/`/`opencode.json` came through on the
  first attempt despite being gitignored upstream. Excluded explicitly.
- 🔴 **`gh pr merge --delete-branch` errors on LOCAL cleanup when `trunk` is checked out in
  another worktree** (`fatal: 'trunk' is already used by worktree at ...`) — **after the
  remote merge has already succeeded**. Check `gh pr view <n> --json state` before reacting;
  do not retry the merge.
- homelab-talos' own `CLAUDE.md` mandates a **dedicated worktree** for commit-to-trunk work
  (its main checkout is permanently dirty). Used one; removed it after.

**Decisions:**

- **`rawConfig` was deliberately NOT converted into a merge.** Consumers rely on replacement
  semantics; silently merging would inject chart-generated keys into a config authored from
  scratch. `configOverlay` is new and additive; setting both **fails the render**.
- The ordering check pins **marker order**, a proxy for section order. A guard that only
  says "A precedes B" **cannot express "B actually runs"** — hence the TERMINAL check pinning
  the blocking gateway loop last.

## How to verify

```bash
cd /home/zach/workspace/kubeclaw
nix-shell -p kubernetes-helm jq "python3.withPackages(p: [p.pyyaml])" --run '
  helm lint . --set agentName=test &&
  helm unittest . &&
  make test-shell && make test-ordering &&
  make render-diff && make byte-diff &&
  make template-all >/dev/null && make template-fleet >/dev/null'
```
Expected: lint clean · `Tests: 189 passed` · `RESULT: 16 passed, 0 failed` ·
`OK: 4 value files, ledgers match, 'Gateway restart loop' last, 13 constraints all exercised` ·
`11/11 identical` · `compared 11 value files`.

CI (the same tiers, on a clean container): `gh run list --branch trunk --limit 3`.

Vendored copy is current: `git -C /home/zach/workspace/homelab-talos show
origin/trunk:containers/clawgate/internal/agents/chart/kubeclaw/Chart.yaml | grep '^version:'`
→ `0.8.0`.
