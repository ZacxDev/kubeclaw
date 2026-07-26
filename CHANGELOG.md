# Changelog

All notable changes to the KubeClaw Helm chart are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
for the chart `version` (the `appVersion` tracks the OpenClaw runtime separately).

Consumers (datapacket-talos hand-authored HelmReleases, ClawSail's Go value
generator, clawgate's vendored chart copy) should read the **Upgrade notes** of
each release for the values to adopt and the boilerplate that can be removed.

## [Unreleased]

## [0.7.1] — 2026-07-25

### Changed
- **NetworkPolicy: fail-loud on an empty allowlist.** `networkPolicy.enabled=true` with no
  `egress.fqdns`/`endpoints`/`entities` now **fails template render** with a clear message,
  instead of silently rendering a default-deny egress that only reaches DNS+apiserver and
  bricks the agent (it looks connected because DNS still resolves). Prevents the silent-brick
  foot-gun. To intentionally allow all egress, leave `networkPolicy.enabled=false`.
- **Docs: GitHub host set.** `matchName` is exact-host, so `github.com` does NOT cover
  `api.github.com` (gh CLI) or `codeload.github.com` (git archive/clone). The values.yaml and
  `ci/full-values.yaml` examples now list the full set so a per-agent config doesn't
  accidentally block `gh`/git.

## [0.7.0] — 2026-07-25

Fleet-hardening as first-class values. Agents can now be hardened through clean
`values.yaml` instead of per-release `postRenderers` + a hand-authored
NetworkPolicy. **Every default is SAFE-by-default** — a default-values render is
backward-compatible with 0.6.0 (proven by a render diff: the only functional
change is the safe container `securityContext`; the openclaw.json config is
byte-identical). Verified by gateway-start on OpenClaw **2026.6.1** AND
**2026.7.1-2** (throwaway containers, same method as 0.6.0).

### Added
- **Container `securityContext` value** (`securityContext`), merged onto the
  `agent` container. **DEFAULT = a safe baseline the chart previously lacked:**
  `allowPrivilegeEscalation: false` + `seccompProfile.type: RuntimeDefault`.
  Verified NON-breaking: gateway-start on both images under
  `--security-opt=no-new-privileges` (the k8s equivalent) keeps `apt-get
  update`, `apt-get install` (dpkg), `git clone`, and `openclaw doctor --fix`
  all succeeding. `capabilities.drop:["ALL"]` is **opt-in, NOT default** — with
  caps dropped, `apt`/`dpkg` fail at init (CapEff=0 → no CHOWN/DAC_OVERRIDE),
  so only agents with deps baked into the image should set it (a commented
  fully-hardened example ships in `values.yaml`). To disable the securityContext
  entirely, set it to `null` (an empty `{}` does not clear it — Helm merges maps).
- **Pod-level `podSecurityContext` value** (empty default → nothing rendered).
  Provided for future non-root work; do NOT set `runAsNonRoot`/`runAsUser`
  without reworking the image — the init script hardcodes writes to
  `/root/.openclaw|.ssh|.kube` and `/usr/local/bin` (UID 0).
- **TLS verification value** (`tls.verify`). The chart used to hardcode
  `NODE_TLS_REJECT_UNAUTHORIZED=0` (all Node TLS verification OFF). It is now
  driven by `tls.verify`. **DEFAULT `false` = "0" (unchanged behavior)** so no
  existing agent breaks; set `tls.verify: true` for verification (renders "1").
  For an internal self-signed endpoint, prefer supplying a CA via
  `NODE_EXTRA_CA_CERTS` (extraEnv) over turning verification off.
- **Egress `CiliumNetworkPolicy` template** (`templates/networkpolicy.yaml`),
  gated on `networkPolicy.enabled` (**default false** — existing agents have no
  policy; a default-deny would break them). When enabled it renders a
  **CiliumNetworkPolicy** (`cilium.io/v2`), EGRESS-ONLY (ingress stays
  default-allow so the gateway port-forward + probes work). Driven by values:
  `egress.fqdns` (FQDN allowlist — exact → `matchName`, `*` → `matchPattern`),
  `egress.fqdnPorts`, `egress.endpoints` (in-cluster `toEndpoints`), plus
  always-allow kube-dns (with the `rules.dns` visibility rule so `toFQDNs`
  resolves) and kube-apiserver. FQDN egress REQUIRES Cilium — `networkPolicy.cilium`
  defaults true and the render fails with a clear message if set false while
  enabled. Server-validated against the live homelab cluster's Cilium CRD
  (`kubectl apply --dry-run=server`). Generalizes the initiatives agent's
  hand-written `network-policy.yaml`.

### Notes
- `tools.web.search.enabled` was already a first-class value (rendered to
  `tools.web.search.enabled` in openclaw.json). Documented: set it `false` for
  restricted-egress agents — it also avoids the search-plugin provider-fetch at
  `openclaw doctor --fix` startup.

### Upgrade notes
- **No values change is required** to upgrade 0.6.0 → 0.7.0. Existing agents get
  the safe container `securityContext` automatically; everything else defaults to
  the prior behavior. (Pods roll once on upgrade because the config checksum
  annotation includes the chart-version label — the openclaw.json is unchanged.)
- **The initiatives agent** can drop its `postRenderers` (TLS env +
  securityContext) and its standalone `network-policy.yaml` in favor of
  `tls.verify: true`, `securityContext.capabilities.drop:["ALL"]`, and
  `networkPolicy.enabled: true` — land that in homelab-talos AFTER the Flux
  `GitRepository` picks up 0.7.0 (see the PR body for the exact diff).
- **clawgate vendors a copy of this chart** at
  `homelab-talos/containers/clawgate/internal/agents/chart/kubeclaw` — sync it
  after adopting this release.

## [0.6.0] — 2026-07-25

Latest-OpenClaw compatibility: native MCP registration + a restricted-egress
doctor/gateway startup fix. Verified against OpenClaw **2026.7.1-2** (current
npm `latest`) AND **2026.6.1** (the backward-compat floor — the initiatives
agent's image).

### Fixed
- **MCP servers used a rejected config key.** The chart emitted a top-level
  `mcpServers` block, which BOTH 2026.7.x and 2026.6.1 reject as an
  unrecognized root key (`config validate` → `<root>: Invalid input`) — so the
  clank-task MCP server could never actually be enabled. MCP servers are now
  emitted under OpenClaw's native `mcp.servers.<name>` key (confirmed against
  `openclaw config schema` on both versions). The stdio `transport` field is
  omitted: 2026.6.1's schema only allows `transport` `sse`/`streamable-http`
  and infers stdio from `command`, while 2026.7.x also accepts an explicit
  `stdio` — omitting it validates on both. `mcpServers.clankTask.enabled=true`
  now renders a config that `openclaw doctor --fix` accepts and preserves.
  *(The values key stays `mcpServers.clankTask.enabled` — only the rendered
  JSON key changed, so existing releases need no values edit.)*
- **`openclaw doctor --fix` / gateway hang under restricted egress
  (openclaw >= 2026.6.11).** Newer OpenClaw does a blocking per-plugin
  npm-registry update-check (`registry.npmjs.org/<pkg>/latest`) at gateway
  start and in `doctor --fix`. For agents whose egress NetworkPolicy does not
  allowlist `registry.npmjs.org`, each fetch has no route and hangs
  (~2.5s × ~49 stock plugins) → doctor never completes → the gateway never
  binds `:18789` → CrashLoopBackOff past the startupProbe budget. The chart now
  emits `update.checkOnStart` (new value `config.updateCheckOnStart`,
  **default `false`**), which disables the check natively. Verified 2026-07-25
  on 2026.7.1-2 with the npm registry black-holed to an unroutable IP:
  check ON → `doctor --fix` times out (90s, rc=124); check OFF → completes in
  ~8s (rc=0) with **zero** registry fetches and the gateway binds `:18789`.
  `OPENCLAW_OFFLINE=1` was tested and does **not** gate this check.

### Upgrade notes
- `config.updateCheckOnStart` defaults to `false` (no npm registry calls at
  startup — safe for hardened, restricted-egress agents; they simply won't
  surface update hints). Set it to `true` only for agents that allowlist
  `registry.npmjs.org` in their NetworkPolicy and want update checks.
- To enable the clank-task MCP server, set `mcpServers.clankTask.enabled=true`
  (now that the emitted key is correct). Schema-accepted on both openclaw
  versions; the live MCP tool round-trip to the clank-resolver API was not
  exercised in chart CI.
- **clawgate vendors a copy of this chart** at
  `homelab-talos/containers/clawgate/internal/agents/chart/kubeclaw` — sync it
  after adopting this release.

## [0.5.2] — 2026-06-07

openclaw 2026.6.x email-plugin compatibility fix.

### Fixed
- **Email plugin install location.** The plugin was copied to
  `node_modules/openclaw/extensions/email`, which openclaw 2026.6.x's plugin
  loader rejects with `extension entry escapes package directory: ./index.js`
  (a fatal "Invalid config" that stops the gateway). It is now installed to
  `node_modules/openclaw/dist/extensions/email` — the stock-extension location —
  so openclaw discovers it cleanly as a stock extension (no path-escape error,
  and no `plugins install` dangerous-code scan). Verified against a live
  `2026.6.1` runtime: the email-enabled config now validates and the gateway
  starts.

### Known gaps (carried)
- On openclaw 2026.6.x the email plugin's openclaw-native channel registration
  is skipped (`bundled channel entry email missing bundled-channel-entry
  contract`). This does not block startup and does not affect agents that use
  email via the Clankup **portal** + `send_email` tool (the homelab fleet's
  model). Full openclaw-native email-channel support needs the plugin updated to
  the 2026.6.x channel-entry contract — tracked follow-up.
- Matrix and clankTask remain default-off pending 2026.6.x schema updates.

## [0.5.1] — 2026-06-06

openclaw 2026.6.x compatibility fix. The chart's default-rendered config was
**rejected by openclaw 2026.6.x**, so the gateway refused to start on a fresh
deploy (verified live against `2026.6.1`). Both offending features now default
OFF, making the default config valid out of the box.

### Changed (default behavior)
- **`channels.matrix.enabled` now defaults to `false`.** openclaw 2026.6.x's
  matrix schema is `additionalProperties: false` and rejects the
  `streamMode` / `typingIndicator` / `dm.*` keys this chart emits, so a
  default-on matrix block makes the gateway fail to start.
- **`mcpServers.clankTask.enabled` now defaults to `false`.** openclaw 2026.6.x
  rejects the `mcpServers` root key (`Unrecognized key: "mcpServers"`).

### Fixed
- Default `helm install` on a current openclaw image (`2026.6.1`) now produces
  a schema-valid `openclaw.json` (root keys: agents, channels[telegram,
  whatsapp], commands, gateway, hooks, messages, tools) — gateway starts clean.
  Validated by rendering defaults and running them through `openclaw doctor` on
  a live `2026.6.1` runtime; 2 helm-unittest regression tests pin it.

### Upgrade notes
- **No action for consumers who already disabled matrix + clankTask** (e.g.
  datapacket/civit) — their rendered config is unchanged.
- **Consumers relying on the old defaults** (matrix-on / clankTask-on) were
  already broken on openclaw 2026.6.x; they now get a valid config without
  matrix/clankTask. Re-enabling either on 2026.6.x is a follow-up (the matrix
  block + MCP registration must be re-expressed in the 2026.6.x schema).

### Known gaps (carried)
- Matrix and clankTask cannot be re-enabled on openclaw 2026.6.x until their
  config blocks are modernized to the new schema.
- Snapshot-enabled agents may restore a stale `openclaw.json` that overrides
  the chart's rendered config — verify the chart config wins on a clean boot.

## [0.5.0] — 2026-06-06

Closes the three "Known gaps" carried over from 0.4.0: no first-class Discord
channel, no pruning of skills removed from values, and the silent
`openclaw.json.last-good` config revert. All additions are opt-in and default
to prior behavior.

### Added
- **`channels.discord`** — first-class Discord channel (native OpenClaw
  support), mirroring the Telegram pattern. Knobs: `enabled` (default false),
  `applicationId`, `dmPolicy` (`pairing`|`allowlist`|`open`|`disabled`),
  `allowFrom` (DM allowlist), `groupPolicy` (`open`|`allowlist`|`disabled`).
  Rendered into `openclaw.json` and added to the startup channel-strip
  allowlist (without which the block would be deleted at boot, like the
  pre-0.4.0 `teams` gap). The bot token is read via OpenClaw's env token
  source — `{"source":"env","provider":"default","id":"DISCORD_BOT_TOKEN"}` —
  so it resolves from the `envFrom` secret with no jq injection. Replaces the
  out-of-chart Discord bridge sidecar datapacket ran.
- **`config.onRevert`** (`warn`|`fail`|`ignore`, default `warn`) — surfaces the
  previously-silent config revert. `openclaw doctor --fix` restores
  `openclaw.json.last-good` when the chart-generated config is schema-invalid,
  so a bad change appears to take while the agent runs the old config. Detection
  is **semantic, not hash-based**: doctor legitimately mutates a valid config
  too (it injects `meta` + a plugins/skills registry), so a file hash always
  changes. Instead, after doctor but BEFORE the channel-strip, the startup
  script verifies the chart's own intended scalars (`agents.defaults.model.primary`,
  `workspace`, `maxConcurrent`, `agents.list[0].id`) from `/config/openclaw.json`
  still match the active config; any mismatch means the release's config did not
  apply. `warn` emits a loud banner
  + a structured `event=config_revert` JSON line + a
  `/root/.openclaw/.config-reverted` sentinel and continues; `fail` additionally
  `exit 1`s so Flux/k8s surface a CrashLoopBackOff; `ignore` keeps today's
  silent behavior (no detection emitted).
- **`pruneStaleSkills`** (default false) — opt-in pruning of chart-managed
  skills removed from `skills`. Uses a SAFE manifest model: a manifest at
  `/data/.chart-skills-manifest` (outside the skills tree, immune to snapshot
  restore) records the skill dirs the chart created. On a later boot, a dir in
  the previous manifest that is no longer in values AND still has a `SKILL.md`
  is deleted. Unmanaged, snapshot-restored, and agent-authored skills are never
  touched (they were never in the manifest). First boot prunes nothing (empty
  manifest) then writes it, so removals take effect on the NEXT restart.
  Credential pruning is intentionally NOT implemented (too risky) — deferred.
- **`make test-shell`** + `tests/shell/` — runtime behavior tests for the
  safety-critical startup-script logic that helm-unittest cannot execute. The
  harness renders the chart, extracts the inline script, rewrites its absolute
  roots to a sandbox, and runs the real prune/revert blocks under `sh` against
  fixtures (16 assertions: stale skill removed + user skill preserved + first-
  boot semantics; revert → banner+sentinel in warn, exit 1 in fail, silent
  no-op in ignore).

### Fixed
- The silent `openclaw.json.last-good` revert is now detectable and escalating
  (was invisible — "settings changed themselves").
- Removing a skill from `skills` can now prune it from the PVC (opt-in), instead
  of leaving an orphaned skill dir forever.

### Upgrade notes
No breaking changes — all additions are opt-in and default to prior behavior.

- **Discord (datapacket out-of-chart bridge):** set `channels.discord.enabled:
  true` (plus `applicationId` / `allowFrom` / policies as needed) and add
  `DISCORD_BOT_TOKEN` to `existingSecret`. You can then **retire the external
  Discord bridge sidecar**. No jq/token wiring needed — the env token source
  resolves from the pod's `envFrom` secret.
- **Config integrity:** keep `config.onRevert: warn` (default) to get a banner +
  `event=config_revert` log line + `.config-reverted` sentinel when doctor
  rejects a config change. For agents where a stale config is worse than an
  outage, set `config.onRevert: fail` so the pod CrashLoopBackOffs and Flux
  shows it not-ready. Set `ignore` to opt out of detection entirely.
- **Skill pruning:** set `pruneStaleSkills: true` to have the chart delete its
  own previously-installed skills once they're removed from `skills`. Note the
  second-boot semantics — the deletion happens on the restart AFTER the manifest
  that recorded the skill was written. Safe to enable alongside snapshots; the
  manifest lives outside snapshot paths.
- **Pinning:** consumers tracking `branch: trunk` can pin to this tag.

### Known gaps (not yet addressed)
- Credential pruning from the PVC on removal from values (deferred from the
  skill-pruning work — credential deletion is higher-risk and needs its own
  manifest + audit story).
- Image staleness: `openclaw-image` builds `openclaw@latest` unpinned with no
  CI; recommend pinning + Renovate in that repo.

## [0.4.0] — 2026-06-06

Consumer-gap release. Closes the most-repeated workarounds found across the three
KubeClaw consumers: hand-rolled OpenRouter auth, silently-dropped agent defaults,
and channels emitted by consumers but stripped by the chart.

### Added
- **`agent.auth.provider`** — first-class auth bootstrap modes.
  `anthropic-oauth` (default, unchanged) | `openrouter` | `apikey`. In
  `openrouter`/`apikey` mode the chart writes an `api_key` profile to
  `agents/<id>/agent/auth-profiles.json` (and `agents/main/`) from a secret env
  var, replacing the per-agent OpenRouter `extraInitCommands`.
  Companion knobs: `agent.auth.providerName`, `agent.auth.profileId`,
  `agent.auth.apiKeyEnv`.
- **`agent.defaults`** (map) — extra keys merged verbatim into
  `agents.defaults` in `openclaw.json` (e.g. `timeoutSeconds`). Previously
  unknown `agent.*` keys were silently dropped.
- **`channels.teams`** — Microsoft Teams channel (`enabled`, `appId`,
  `tenantId`), rendered into `openclaw.json` and added to the startup
  channel-strip allowlist. ClawSail already emitted `channels.teams.*`; it was
  being deleted at boot.
- **`channels.whatsapp.allowFrom`** — pre-approved WhatsApp sender IDs, now
  rendered into `channels.whatsapp.allowFrom` (was previously dropped).
- **`rbac.clusterReadOnly.enabled`** — binds the agent ServiceAccount to the
  built-in cluster `view` ClusterRole for read-only diagnostics across
  namespaces, replacing hand-rolled per-agent read-only RBAC.
- **`replicaCount`** — documented in `values.yaml` (was an undocumented
  contract; `0` provisions resources without running the pod).
- **`CHANGELOG.md`** — this file. Semver-tagged releases give consumers a
  pinnable, auditable upgrade path instead of tracking `trunk` live.

### Fixed
- `channels.teams` and `channels.whatsapp.allowFrom` are no longer silently
  discarded between config generation and the startup channel-strip.
- `replicaCount: 0` is now honored. The deployment used
  `{{ .Values.replicaCount | default 1 }}`, and Helm's `default` treats `0` as
  empty — so "save for later" (0 replicas, used by clawgate) silently ran 1
  replica. Now rendered as `{{ .Values.replicaCount }}` with the default in
  values.yaml.

### Upgrade notes
No breaking changes — all additions are opt-in and default to prior behavior.

- **OpenRouter / API-key agents (datapacket-talos):** set
  `agent.auth.provider: openrouter` and ensure `OPENROUTER_API_KEY` is in
  `existingSecret`. You can then **delete the OpenRouter `extraInitCommands`**
  block (the `rm` of Claude creds + `jq` auth-profile rebuild into the agent and
  `main` dirs). For other providers use `provider: apikey` with `providerName`
  and `apiKeyEnv`.
- **Custom agent defaults (e.g. `timeoutSeconds`):** move them from
  `extraInitCommands` jq-patching into `agent.defaults: { timeoutSeconds: 600 }`.
- **ClawSail:** `channels.teams.*` and `channels.whatsapp.allowFrom` now take
  effect — no chart-side change needed beyond bumping to 0.4.0.
- **Read-only agents:** replace per-agent `rbac-readonly.yaml` with
  `rbac.clusterReadOnly.enabled: true`.
- **Pinning:** consumers tracking `branch: trunk` can pin to this tag. The
  OpenClaw runtime image (`image.tag`) remains separate — pin it to a real
  version (e.g. `2026.6.1`) rather than `latest` for reproducible deploys.

### Known gaps (not yet addressed)
- No first-class Discord channel (datapacket runs an out-of-chart bridge sidecar).
- Removing a skill/credential from values does not prune it from the PVC.
- `openclaw.json.last-good` silently reverts schema-invalid edits (no surfaced error).
- Image staleness: `openclaw-image` builds `openclaw@latest` unpinned with no CI;
  recommend pinning + Renovate in that repo.

[Unreleased]: https://github.com/ZacxDev/kubeclaw/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/ZacxDev/kubeclaw/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/ZacxDev/kubeclaw/releases/tag/v0.4.0
