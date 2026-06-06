# Changelog

All notable changes to the KubeClaw Helm chart are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
for the chart `version` (the `appVersion` tracks the OpenClaw runtime separately).

Consumers (datapacket-talos hand-authored HelmReleases, ClawSail's Go value
generator, clawgate's vendored chart copy) should read the **Upgrade notes** of
each release for the values to adopt and the boilerplate that can be removed.

## [Unreleased]

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

[Unreleased]: https://github.com/ZacxDev/kubeclaw/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/ZacxDev/kubeclaw/releases/tag/v0.4.0
