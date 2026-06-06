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
echo
printf 'RESULT: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
