#!/usr/bin/env bash
# Runtime behavior tests for the safety-critical parts of the devpod startup
# script that helm-unittest cannot cover (it only asserts on rendered text).
#
# Strategy: render the chart, extract the relevant inline-script block
# (tests/shell/extract_block.py), rewrite the two absolute roots the script
# uses (/root/.openclaw and /data) to a throwaway sandbox, then execute the
# block under `sh` against fixture directories and assert on the result.
#
# This proves the ACTUAL rendered logic — not a re-implementation.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
CHART_DIR="$(cd "$HERE/../.." >/dev/null 2>&1 && pwd)"
cd "$CHART_DIR" >/dev/null 2>&1 || exit 1

PASS=0
FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   - %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL - %s\n' "$1"; }

# Render a block and rewrite the absolute roots to the sandbox so the real
# logic runs without touching the host filesystem. Order matters: rewrite the
# longer, more specific path (/root/.openclaw) before /root, and /data last.
prepare_block() {
  block="$1"; sandbox="$2"; shift 2
  python3 "$HERE/extract_block.py" --block "$block" "$@" \
    | sed -e "s#/root/.openclaw#${sandbox}/root/.openclaw#g" \
          -e "s#/config/openclaw.json#${sandbox}/config/openclaw.json#g" \
          -e "s#/data#${sandbox}/data#g"
}

# ---------------------------------------------------------------------------
echo "== Gap B: prune stale chart-managed skills =="

# Scenario 1: a skill the chart created previously but is no longer in values
# is pruned; an unmanaged (agent-authored / snapshot-restored) skill survives.
SB="$(mktemp -d)"
mkdir -p "$SB/root/.openclaw/skills" "$SB/data" "$SB/config/skills"
# Current values ship only "alpha".
printf 'alpha skill\n' > "$SB/config/skills/alpha.md"
# Previous boot installed alpha + beta (both chart-managed) -> manifest.
printf 'alpha\nbeta\n' > "$SB/data/.chart-skills-manifest"
# beta exists on disk with a SKILL.md (chart-installed last boot).
mkdir -p "$SB/root/.openclaw/skills/beta"
printf 'beta skill\n' > "$SB/root/.openclaw/skills/beta/SKILL.md"
# user-authored skill: NOT in manifest -> must never be touched.
mkdir -p "$SB/root/.openclaw/skills/userskill"
printf 'user skill\n' > "$SB/root/.openclaw/skills/userskill/SKILL.md"

# Rewrite /config/skills too for this block (the install loop reads it).
python3 "$HERE/extract_block.py" --block prune --set pruneStaleSkills=true \
  | sed -e "s#/root/.openclaw#${SB}/root/.openclaw#g" \
        -e "s#/config/skills#${SB}/config/skills#g" \
        -e "s#/data#${SB}/data#g" \
  | sh 2>"$SB/err.log"

if [ ! -e "$SB/root/.openclaw/skills/beta" ]; then
  ok "stale chart-managed skill 'beta' pruned"
else
  bad "stale chart-managed skill 'beta' was NOT pruned"
fi
if [ -f "$SB/root/.openclaw/skills/userskill/SKILL.md" ]; then
  ok "unmanaged skill 'userskill' preserved"
else
  bad "unmanaged skill 'userskill' was wrongly deleted"
fi
if [ -f "$SB/root/.openclaw/skills/alpha/SKILL.md" ]; then
  ok "current skill 'alpha' installed"
else
  bad "current skill 'alpha' missing"
fi
# Manifest rewritten to current set (alpha only).
if grep -qxF alpha "$SB/data/.chart-skills-manifest" \
   && ! grep -qxF beta "$SB/data/.chart-skills-manifest"; then
  ok "manifest rewritten to current chart-managed set"
else
  bad "manifest not rewritten correctly: $(tr '\n' ',' < "$SB/data/.chart-skills-manifest")"
fi
rm -rf "$SB"

# Scenario 2: first boot (no manifest) prunes nothing, then writes manifest.
SB="$(mktemp -d)"
mkdir -p "$SB/root/.openclaw/skills" "$SB/data" "$SB/config/skills"
printf 'alpha skill\n' > "$SB/config/skills/alpha.md"
# Pre-existing snapshot-restored skill, no manifest yet.
mkdir -p "$SB/root/.openclaw/skills/restored"
printf 'restored\n' > "$SB/root/.openclaw/skills/restored/SKILL.md"
python3 "$HERE/extract_block.py" --block prune --set pruneStaleSkills=true \
  | sed -e "s#/root/.openclaw#${SB}/root/.openclaw#g" \
        -e "s#/config/skills#${SB}/config/skills#g" \
        -e "s#/data#${SB}/data#g" \
  | sh 2>/dev/null
if [ -f "$SB/root/.openclaw/skills/restored/SKILL.md" ]; then
  ok "first boot (empty manifest) prunes nothing"
else
  bad "first boot wrongly pruned a pre-existing skill"
fi
if [ -f "$SB/data/.chart-skills-manifest" ] && grep -qxF alpha "$SB/data/.chart-skills-manifest"; then
  ok "first boot writes manifest"
else
  bad "first boot did not write manifest"
fi
rm -rf "$SB"

# ---------------------------------------------------------------------------
echo "== Gap C: silent config-revert detection =="

# Helper: drive the revert block. doctor is stubbed to a no-op (DOCTOR_HOOK=':')
# — we seed the POST-doctor active config directly, since that is what the
# semantic detection inspects (it compares chart-intended scalars in
# /config/openclaw.json against the active /root/.openclaw/openclaw.json).
run_revert() {
  mode="$1"; doctor_hook="$2"; sandbox="$3"
  prepare_block revert "$sandbox" --set "config.onRevert=$mode" \
    > "$sandbox/block.sh"
  DOCTOR_HOOK="$doctor_hook" sh "$sandbox/block.sh" \
    > "$sandbox/out.log" 2>"$sandbox/err.log"
  echo $? > "$sandbox/exit.code"
}

# Chart-intended config (/config/openclaw.json) — the values this release renders.
_CHART_CFG='{"agents":{"defaults":{"model":{"primary":"openrouter/new-model"},"workspace":"/data/workspace","maxConcurrent":2},"list":[{"id":"a1"}]}}'
# Active AFTER doctor accepted it: chart scalars preserved, doctor adds junk.
_ACTIVE_OK='{"agents":{"defaults":{"model":{"primary":"openrouter/new-model"},"workspace":"/data/workspace","maxConcurrent":2,"auth":{}},"list":[{"id":"a1"}]},"meta":{"lastTouchedVersion":"x"},"plugins":{"entries":{}}}'
# Active AFTER a revert: doctor restored an OLD config (different model).
_ACTIVE_REVERTED='{"agents":{"defaults":{"model":{"primary":"openrouter/OLD-model"},"workspace":"/data/workspace","maxConcurrent":2},"list":[{"id":"a1"}]},"meta":{"lastTouchedVersion":"x"}}'
seed_cfg() {  # $1=sandbox  $2=active-json
  mkdir -p "$1/root/.openclaw" "$1/config"
  printf '%s\n' "$_CHART_CFG" > "$1/config/openclaw.json"
  printf '%s\n' "$2"          > "$1/root/.openclaw/openclaw.json"
}

# --- warn: revert (active has OLD model) -> banner + sentinel, exit 0 ---
SB="$(mktemp -d)"; seed_cfg "$SB" "$_ACTIVE_REVERTED"
run_revert warn ':' "$SB"
EC=$(cat "$SB/exit.code")
if grep -q 'CONFIG REVERT DETECTED' "$SB/err.log"; then ok "warn: banner emitted"; else bad "warn: no banner"; fi
if grep -q '"event":"config_revert"' "$SB/out.log"; then ok "warn: structured JSON event emitted"; else bad "warn: no JSON event"; fi
if [ -f "$SB/root/.openclaw/.config-reverted" ]; then ok "warn: sentinel file written"; else bad "warn: no sentinel"; fi
if [ "$EC" = "0" ]; then ok "warn: exit 0 (continues)"; else bad "warn: expected exit 0, got $EC"; fi
rm -rf "$SB"

# --- fail: same revert -> banner + sentinel, but exit 1 ---
SB="$(mktemp -d)"; seed_cfg "$SB" "$_ACTIVE_REVERTED"
run_revert fail ':' "$SB"
EC=$(cat "$SB/exit.code")
if grep -q 'CONFIG REVERT DETECTED' "$SB/err.log"; then ok "fail: banner emitted"; else bad "fail: no banner"; fi
if [ "$EC" = "1" ]; then ok "fail: exit 1 (CrashLoopBackOff)"; else bad "fail: expected exit 1, got $EC"; fi
rm -rf "$SB"

# --- warn, NO revert: doctor accepted (chart scalars present) -> silent ---
# This is the case that BROKE the original hash approach: doctor mutates the
# file (adds meta/plugins), but the chart's settings are intact, so NO revert.
SB="$(mktemp -d)"; seed_cfg "$SB" "$_ACTIVE_OK"
printf '{"reverted":true}\n' > "$SB/root/.openclaw/.config-reverted"  # stale sentinel
run_revert warn ':' "$SB"
EC=$(cat "$SB/exit.code")
if ! grep -q 'CONFIG REVERT DETECTED' "$SB/err.log"; then ok "no-revert: no false-positive banner (doctor-mutated but accepted)"; else bad "no-revert: false-positive banner"; fi
if [ ! -f "$SB/root/.openclaw/.config-reverted" ]; then ok "no-revert: stale sentinel cleared"; else bad "no-revert: stale sentinel not cleared"; fi
if [ "$EC" = "0" ]; then ok "no-revert: exit 0"; else bad "no-revert: expected exit 0, got $EC"; fi
rm -rf "$SB"

# --- ignore: block must be absent entirely (no detection) ---
SB="$(mktemp -d)"
mkdir -p "$SB/root/.openclaw"
if prepare_block revert "$SB" --set config.onRevert=ignore | grep -q 'CONFIG REVERT DETECTED'; then
  bad "ignore: revert block present (should be omitted)"
else
  ok "ignore: revert detection omitted from script"
fi
rm -rf "$SB"

# ---------------------------------------------------------------------------
echo "== Gap D: the auto-pull dirty-skip must be VISIBLE =="

# A dirty-skip lasts until a human clears the tree, and it used to log nothing.
# Measured: one tracked edit left in the civitai devops-agent's clone at
# 2026-05-28T17:03Z froze it for 102 days while the loop kept cycling normally.
# These cases pin that a skip announces itself ONCE, names what blocks it, stays
# quiet on subsequent cycles, and says so when it resumes.

GS_SB="$(mktemp -d)"
GS_ORIGIN="$GS_SB/origin.git"
GS_REPO="$GS_SB/data/repos/fixture"
GS_LOG="$GS_SB/tmp/git-sync.log"
gitq() { git -c user.email=t@example.invalid -c user.name=t -c commit.gpgsign=false "$@"; }

mkdir -p "$GS_SB/tmp" "$GS_SB/config" "$GS_SB/data/repos"
gitq init --quiet --bare -b main "$GS_ORIGIN"
gitq init --quiet -b main "$GS_SB/seed"
gitq -C "$GS_SB/seed" remote add origin "$GS_ORIGIN"
printf 'v1\n' > "$GS_SB/seed/tracked.txt"
gitq -C "$GS_SB/seed" add tracked.txt
gitq -C "$GS_SB/seed" commit --quiet -m seed
gitq -C "$GS_SB/seed" push --quiet -u origin main
gitq clone --quiet -b main "$GS_ORIGIN" "$GS_REPO"
gitq -C "$GS_REPO" config user.email t@example.invalid
gitq -C "$GS_REPO" config user.name t
printf '[{"url":"%s","path":"%s","branch":"main"}]\n' "$GS_ORIGIN" "$GS_REPO" \
  > "$GS_SB/config/repos.json"

gs_advance() {  # push one commit so there is always something to pull
  printf '%s\n' "$1" >> "$GS_SB/seed/tracked.txt"
  gitq -C "$GS_SB/seed" commit --quiet -am "$1"
  gitq -C "$GS_SB/seed" push --quiet origin main
}
gs_run() {  # $1 = number of loop cycles to execute
  python3 "$HERE/extract_block.py" --block gitsync \
    | sed -e "s#/config/repos.json#${GS_SB}/config/repos.json#g" \
          -e "s#/tmp/git-sync#${GS_SB}/tmp/git-sync#g" \
    > "$GS_SB/block.sh"
  GIT_SYNC_ITERS="$1" sh "$GS_SB/block.sh" >/dev/null 2>&1
}
gs_head()   { gitq -C "$GS_REPO" rev-parse HEAD; }
gs_remote() { gitq -C "$GS_SB/seed" rev-parse HEAD; }
gs_marks()  { ls "$GS_SB"/tmp/git-sync-dirty.* 2>/dev/null | wc -l | tr -d ' '; }
# `grep -c` PRINTS 0 and EXITS 1 on no match, so a `|| echo 0` fallback emits
# "0\n0" and every arithmetic comparison downstream errors out. Guard on the
# file existing instead, and let grep's own 0 stand.
gs_skips()  { [ -f "$GS_LOG" ] || { echo 0; return; }; grep -c 'git-sync: SKIPPING' "$GS_LOG"; }

# --- clean tree pulls. Invariant guard: this passed before this change too,
#     and is here so a failure elsewhere in Gap D can be attributed. ---
gs_advance c1
gs_run 1
if grep -q 'git-sync: pulled' "$GS_LOG" && [ "$(gs_head)" = "$(gs_remote)" ]; then
  ok "clean tree pulls (invariant guard, not regression coverage)"
else
  bad "clean tree did not pull"
fi

# --- dirty tracked file: the skip must announce itself and name the file ---
gs_advance c2
printf 'agent WIP\n' >> "$GS_REPO/tracked.txt"
GS_BEFORE="$(gs_head)"
gs_run 1
if [ "$(gs_skips)" -ge 1 ]; then ok "dirty tree announces the skip"; else bad "dirty-skip was SILENT"; fi
if grep 'git-sync: SKIPPING' "$GS_LOG" 2>/dev/null | grep -q 'tracked.txt'; then
  ok "skip names the blocking file"
else
  bad "skip does not name the blocking file"
fi
if [ "$(gs_marks)" = "1" ]; then ok "stuck-since marker written"; else bad "no stuck-since marker"; fi
if [ "$(gs_head)" = "$GS_BEFORE" ]; then ok "dirty tree still not pulled over"; else bad "dirty tree WAS pulled over"; fi

# --- still dirty, 3 more cycles: transition-logged, not per-cycle ---
gs_advance c3
gs_run 3
GS_N="$(gs_skips)"
if [ "$GS_N" = "1" ]; then
  ok "skip logs once, not once per cycle (3 further cycles added 0 lines)"
else
  bad "expected exactly 1 SKIPPING line after 4 dirty cycles, got $GS_N"
fi

# --- tree cleaned: resume is announced, marker cleared, pull happens ---
gitq -C "$GS_REPO" checkout -- tracked.txt
gs_run 1
if grep -q 'clean again, resuming' "$GS_LOG"; then ok "resume is announced"; else bad "resume not announced"; fi
if [ "$(gs_marks)" = "0" ]; then ok "marker cleared on resume"; else bad "marker not cleared on resume"; fi
if [ "$(gs_head)" = "$(gs_remote)" ]; then ok "pull resumes once the tree is clean"; else bad "did not pull after cleaning"; fi

# --- untracked runtime files must NOT block a pull (the tracked/untracked
#     distinction the dirty-skip comment claims) ---
gs_advance c4
printf 'runtime\n' > "$GS_REPO/HEARTBEAT.md"
gs_run 1
if [ "$(gs_head)" = "$(gs_remote)" ]; then ok "untracked runtime file does not block the pull"; else bad "untracked file blocked the pull"; fi
if [ "$(gs_marks)" = "0" ]; then ok "untracked file writes no stuck marker"; else bad "untracked file wrongly marked stuck"; fi
rm -rf "$GS_SB"

# ---------------------------------------------------------------------------
echo
printf 'RESULT: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
