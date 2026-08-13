<p align="center">
  <img src="logo.svg" alt="KubeClaw Logo" width="200">
</p>

<h1 align="center">KubeClaw</h1>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://helm.sh"><img src="https://img.shields.io/badge/Helm-v3-blue" alt="Helm"></a>
</p>

<p align="center">A lightweight, composable Kubernetes control plane for <a href="https://github.com/ZacxDev/openclaw-image">OpenClaw</a> AI agent fleets.</p>

Deploy an agent in **2 files** instead of 8+ — then govern it like infrastructure. One values file defines an agent's isolation boundary, RBAC tier, egress allowlist, backup policy, and scheduled work. Add the next agent by writing another one.

## Composition Model

Every capability is an independent opt-in block. A minimal agent renders 10 Kubernetes objects; turning everything on renders 19 — you pay only for what you enable.

| Block | Values | What it adds |
|-------|--------|--------------|
| **Channels** | `channels.*` | Matrix, Telegram, Discord, WhatsApp, Teams, SMS, email (all off by default) |
| **Skills** | `skills`, `pruneStaleSkills` | Markdown instruction files, installed and optionally pruned on redeploy |
| **Workspace** | `workspaceFiles`, `workspaceContent` | Files fetched from URLs or written inline at startup |
| **Workflows** | `workflows` | A CronJob per pipeline + scoped exec RBAC |
| **Snapshots** | `snapshots` | Scheduled + preStop saves to S3, startup restore, retention, encryption |
| **Hardening** | `securityContext`, `tls`, `networkPolicy` | seccomp baseline, TLS verification, per-agent egress allowlist |
| **RBAC tier** | `rbac.*` | namespace reader → cluster `view` → orchestrator → cluster-admin |
| **Observability** | `logShipping` | Sidecars tailing logs, stability bundles and trajectories to stdout |
| **Escape hatches** | `extraConfigMaps`, `extraVolumes`, `extraEnv`, `extraInitCommands`, `rawConfig` | Arbitrary Kubernetes objects, or a full `openclaw.json` override |

### What KubeClaw is not

**OpenClaw is the agent runtime** — the model loop, tools, and channel handling all run inside the container image. KubeClaw is the layer that deploys, configures and governs it: namespaces, RBAC, egress, storage, scheduling, and config generation. Swapping in a different agent would mean rewriting the config generation and the CLI contract, not just changing the image.

## How It Works

KubeClaw deploys an OpenClaw agent pod that:

1. Clones your git repos via SSH (and keeps them pulled in the background)
2. Connects to a chat channel — Matrix, Telegram, Discord, WhatsApp, Teams, SMS, or email
3. Listens for messages and executes skills (markdown instruction files)
4. Optionally runs scheduled multi-step workflows via CronJobs
5. Optionally snapshots its workspace to S3, ships logs to Loki, and runs under an egress allowlist

Each agent gets its own namespace (`devpod-{name}`), persistent storage, service account, and service endpoint.

> **All channels default to off.** Enable exactly the one you want. In particular `channels.matrix.enabled` defaults to `false`: openclaw 2026.6.x's matrix schema is `additionalProperties: false` and rejects keys this chart emits, so a default-on matrix block makes the gateway refuse to start.

**Compatibility:** tested against OpenClaw **2026.6.1** and **2026.7.1-2**. The chart encodes several version-specific workarounds — config key naming, plugin install path, the startup update-check — so pin your image tag and read the `CHANGELOG.md` upgrade notes before bumping.

## Minimal Example

A working agent needs just an `agentName`, a git repo, and a secret:

```yaml
# helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: myagent
  namespace: flux-system
spec:
  targetNamespace: devpod-myagent
  install:
    createNamespace: true
  chart:
    spec:
      chart: .
      sourceRef:
        kind: GitRepository
        name: kubeclaw
        namespace: flux-system
  values:
    agentName: myagent

    image:
      repository: your-registry/openclaw

    git:
      repos:
        - url: "git@github.com:yourorg/myproject.git"
          path: "/data/repos/myproject"

    channels:
      telegram:
        enabled: true

    skills:
      myagent.md: |
        # My Agent
        You are a dev agent for myproject at /data/repos/myproject.

    existingSecret: devpod-secrets
```

```yaml
# devpod-secrets.enc.yaml (SOPS-encrypted)
apiVersion: v1
kind: Secret
metadata:
  name: devpod-secrets
  namespace: devpod-myagent
stringData:
  TELEGRAM_BOT_TOKEN: "123456:ABC-..."
  GITHUB_TOKEN: "ghp_..."
  git-ssh-key: |
    -----BEGIN OPENSSH PRIVATE KEY-----
    ...
  claude-credentials.json: |
    {"oauth_token": "..."}
```

Commit both files, push, and Flux deploys a running agent.

## Adding a Workflow

Workflows are scheduled multi-step pipelines. Add a `workflows` block to run agent tasks on a cron schedule:

```yaml
# Add to your HelmRelease values:
workflows:
  daily-summary:
    schedule: "0 9 * * 1-5"        # 9 AM UTC, weekdays
    notify:
      telegram:
        chatId: "123456789"
    steps:
      - name: summarize
        notify: true
        timeout: 300
        skill: |
          Summarize the latest commits in /data/repos/myproject.
          Format for Telegram, keep it under 3000 chars.
```

This creates a CronJob that `kubectl exec`s into the agent pod, runs the skill, and sends the output to Telegram.

Workflows support multiple sequential steps, automatic git report commits, and context variables passed between steps. See `examples/workflow-product-iteration.yaml` for a multi-step example.

## Agent Variants

| Variant | Use Case | Key Config |
|---------|----------|------------|
| **Standard** | Dev agent with git repos and skills | Default setup |
| **Coordinator** | Routes tasks to other agents | `extraConfigMaps` with agent registry |
| **Read-only diagnostic** | Cluster-wide `get`/`describe`/`logs`, no writes | `rbac.clusterReadOnly.enabled: true`, `infraTools.enabled: true` |
| **Orchestrator** | Cross-namespace workflow management | `rbac.orchestrator.enabled: true`, `infraTools.enabled: true` |
| **Infrastructure** | Cluster admin with kubectl/flux/sops | `infraTools.enabled: true`, `rbac.clusterAdmin.enabled: true` |

See `examples/` for complete configurations of each variant, and
[`examples/fleet/`](examples/fleet/) for three agents at three different trust
tiers deployed from the same chart — the composition model above, made concrete.

## What Gets Created

For every agent:

| Resource | Name | Purpose |
|----------|------|---------|
| Namespace | `devpod-{name}` | Isolation |
| Deployment | `{name}-devpod` | Agent pod with startup script |
| Service | `{name}-devpod` | ClusterIP — port 18789 (gateway), 18790 (skills API) |
| PVC | `{name}-data` | Persistent storage (10Gi, opt-in via `persistence.enabled`) |
| ConfigMap | `{name}-config` | Generated `openclaw.json` + `repos.json` |
| ConfigMap | `{name}-skills` | Skill markdown files |
| ConfigMap | `{name}-clank-task-{cli,mcp}` | `clank-task` CLI + MCP stdio server binaries |
| ServiceAccount | `{name}-devpod` | Pod identity |
| Role + RoleBinding | `{name}-reader` | Namespace read access |

Optional resources:
- **ClusterRoleBinding** `{name}-devpod-admin` to cluster-admin (when `rbac.clusterAdmin.enabled: true`)
- **ClusterRoleBinding** `{name}-view` to the built-in `view` role (when `rbac.clusterReadOnly.enabled: true`)
- **ClusterRole + ClusterRoleBinding** `{name}-orchestrator` (when `rbac.orchestrator.enabled: true` and `clusterAdmin` is disabled)
- **CiliumNetworkPolicy** `{name}-egress` (when `networkPolicy.enabled: true`)
- **CronJob** per workflow + shared workflow RBAC (when `workflows` is defined)
- **CronJob** for email polling (when `channels.email.enabled: true`)
- **CronJob** for workspace snapshots (when `snapshots.enabled: true`)
- **Log-shipping sidecars** on the agent pod (when `logShipping.enabled: true`)

## Values Reference

### Core

| Value | Default | Description |
|-------|---------|-------------|
| `agentName` | **required** | Agent name, used for all resource naming |
| `replicaCount` | `1` | Set to `0` to provision every resource without running the pod (a paused / "save for later" agent) |
| `image.repository` | `your-registry/openclaw` | Container image |
| `image.tag` | `latest` | Image tag |
| `existingSecret` | `""` | Secret name with tokens and keys |

### Agent

| Value | Default | Description |
|-------|---------|-------------|
| `agent.model.primary` | `anthropic/claude-sonnet-4` | Claude model |
| `agent.maxConcurrent` | `4` | Max concurrent sessions |
| `agent.mentionPatterns` | `["@{name}", "{name}"]` | Chat mention triggers |
| `agent.workspace` | First repo path | Working directory |
| `agent.thinkingDefault` | `""` | `off`/`minimal`/`low`/`medium`/`high`; empty uses the model default. Lower it for reasoning models that burn their output budget on reasoning and emit empty turns |
| `agent.defaults` | `{}` | Extra keys merged verbatim into `agents.defaults` in `openclaw.json` (e.g. `timeoutSeconds`). Previously, unknown `agent.*` keys were silently dropped |
| `agent.auth.provider` | `anthropic-oauth` | Which credential profile is written to `auth-profiles.json`. `anthropic-oauth` builds an OAuth profile from `claude-credentials.json`; `openrouter` builds an api_key profile from `OPENROUTER_API_KEY`; `apikey` is the generic form (`providerName` + `apiKeyEnv`) |

### Git

| Value | Default | Description |
|-------|---------|-------------|
| `git.email` | `agent@devpod.local` | Commit author email |
| `git.name` | `DevPod Agent` | Commit author name |
| `git.repos` | `[]` | Repos to clone: `[{url, path, branch}]` |
| `git.autoPull.enabled` | `true` | Background fetch+pull loop for workspace repos |
| `git.autoPull.intervalSeconds` | `300` | Interval between auto-pull cycles |

### Channels

All channels are **off by default** — enable the one you want.

| Value | Default | Description |
|-------|---------|-------------|
| `channels.matrix.enabled` | `false` | Enable Matrix. Off by default because openclaw 2026.6.x's matrix schema rejects the `streamMode`/`typingIndicator`/`dm.*` keys this chart emits and the gateway then refuses to start |
| `channels.matrix.homeserver` | `https://matrix.example.com` | Matrix server URL |
| `channels.telegram.enabled` | `false` | Enable Telegram |
| `channels.telegram.allowFrom` | `[]` | Pre-approved Telegram user IDs (skips pairing) |
| `channels.discord.enabled` | `false` | Enable Discord (native OpenClaw support; token read from `DISCORD_BOT_TOKEN` via env token source, no jq injection) |
| `channels.discord.dmPolicy` | `pairing` | `pairing`, `allowlist`, `open`, or `disabled` |
| `channels.discord.groupPolicy` | `allowlist` | `open`, `allowlist`, or `disabled` |
| `channels.whatsapp.enabled` | `false` | Enable WhatsApp (Baileys, credentials persisted on PVC) |
| `channels.teams.enabled` | `false` | Enable Microsoft Teams (`appId` + `tenantId`) |
| `channels.sms.enabled` | `false` | Enable SMS (Twilio) |
| `channels.email.enabled` | `false` | Enable email channel (Mailpit poller CronJob) |

### MCP Servers

| Value | Default | Description |
|-------|---------|-------------|
| `mcpServers.clankTask.enabled` | `false` | Register `clank-task-mcp` stdio server with OpenClaw (emitted under the native `mcp.servers.<name>` key) for typed task tools |

### Config Lifecycle

| Value | Default | Description |
|-------|---------|-------------|
| `config.onRevert` | `warn` | What to do when `openclaw doctor --fix` silently reverts `openclaw.json` to `openclaw.json.last-good` because the generated config was rejected. `warn` logs a banner + a structured `event=config_revert` line + a `/root/.openclaw/.config-reverted` sentinel and continues; `fail` also exits 1 so the pod CrashLoopBackOffs and Flux surfaces it; `ignore` restores the old silent behavior |
| `config.updateCheckOnStart` | `false` | Emit `update.checkOnStart`. When `false`, OpenClaw skips the npm-registry update check at gateway/`doctor` start — required for agents whose egress does not allowlist `registry.npmjs.org` (otherwise startup hangs on openclaw >= 2026.6.11) |

### Hardening

Every default here is backward-compatible — upgrading an existing agent changes only the container `securityContext`.

| Value | Default | Description |
|-------|---------|-------------|
| `securityContext` | `allowPrivilegeEscalation: false`, `seccompProfile.type: RuntimeDefault` | Merged onto the agent container. Set to `null` to render none — an empty `{}` does **not** clear it (Helm deep-merges maps). `capabilities.drop: ["ALL"]` is opt-in: it breaks `apt-get`/dpkg at init, so only use it on images with deps baked in |
| `podSecurityContext` | `{}` | Pod-level securityContext. Do **not** set `runAsNonRoot`/`runAsUser` without reworking the image — the startup script writes to `/root/.*` and `/usr/local/bin` as UID 0 |
| `tls.verify` | `false` | `false` → `NODE_TLS_REJECT_UNAUTHORIZED=0` (verification off — the chart's historical hardcoded behavior). Recommended to flip to `true` per agent; for internal self-signed endpoints supply a CA via `NODE_EXTRA_CA_CERTS` in `extraEnv` instead |
| `networkPolicy.enabled` | `false` | Render an egress-only `CiliumNetworkPolicy` (ingress stays default-allow so probes/port-forwards work) |
| `networkPolicy.egress.fqdns` | `[]` | FQDN allowlist. Entries with `*` render as `matchPattern`, otherwise `matchName` |
| `networkPolicy.egress.endpoints` | `[]` | In-cluster egress: `[{namespace, labels, ports}]` |

Two guards fail the render rather than shipping a silently broken agent:
- Enabling `networkPolicy` with an **empty** allowlist fails. A default-deny egress reaching only DNS + apiserver bricks the agent while looking connected, because DNS still resolves. To allow all egress, leave it disabled.
- `networkPolicy.cilium: false` while enabled fails — `toFQDNs` cannot be expressed in a plain `networking.k8s.io` NetworkPolicy.

`matchName` is **exact-host**: `github.com` does not cover `api.github.com` (gh CLI) or `codeload.github.com` (git archive/clone). List every host the agent actually uses.

### Observability

| Value | Default | Description |
|-------|---------|-------------|
| `logShipping.enabled` | `false` | Run busybox sidecars that tail openclaw logs, stability bundles, and per-session trajectories to stdout for cluster log collection (e.g. Grafana Alloy → Loki) |

### Gateway

| Value | Default | Description |
|-------|---------|-------------|
| `gateway.http.endpoints.chatCompletions.enabled` | `true` | Enable OpenAI-compatible `/v1/chat/completions` |
| `gateway.http.endpoints.responses.enabled` | `true` | Enable OpenAI Responses `/v1/responses` (structured tool calls) |

### Skills

| Value | Default | Description |
|-------|---------|-------------|
| `skills` | `{}` | `filename.md: content` map, mounted at `/config/skills/` and installed to `/root/.openclaw/skills/{filename-stem}/SKILL.md` (the map key, **not** the frontmatter `name:`) |
| `pruneStaleSkills` | `false` | Delete chart-managed skill dirs that were removed from `skills`. Manifest-based, so unmanaged / snapshot-restored / agent-authored skills are never touched. Takes effect on the *next* restart after the manifest is written |

### Workspace Files

| Value | Default | Description |
|-------|---------|-------------|
| `workspaceFiles` | `[]` | `[{path, url}]` — downloaded into the workspace at startup (typically pre-signed S3 URLs) |
| `workspaceContent` | `{}` | `path: content` — inline files written into the workspace at startup (e.g. `AGENTS.md`, `CLAUDE.md`) |

### Snapshots

| Value | Default | Description |
|-------|---------|-------------|
| `snapshots.enabled` | `false` | Back up workspace paths to S3-compatible storage via rclone |
| `snapshots.provider` | `s3` | `s3`, `minio`, or `r2` (`endpoint` required for the latter two) |
| `snapshots.bucket` | `""` | Bucket name (required when enabled) |
| `snapshots.paths` | `["/data/workspace"]` | Directories to snapshot |
| `snapshots.save.schedule` | `0 */6 * * *` | CronJob schedule for scheduled saves |
| `snapshots.save.onShutdown` | `true` | Save via a preStop hook (extends `terminationGracePeriodSeconds`) |
| `snapshots.restore.onStartup` | `true` | Restore from the latest snapshot on first boot |
| `snapshots.retention.maxCount` | `5` | Keep N newest; older ones deleted after a successful save |
| `snapshots.encryption.enabled` | `false` | Client-side rclone crypt (needs `SNAPSHOT_ENCRYPTION_PASSWORD`) |

Drop a `.snapshotignore` file (rclone exclude patterns, one per line) in a snapshot path root and it is picked up automatically.

### Hooks

| Value | Default | Description |
|-------|---------|-------------|
| `hooks.enabled` | `true` | Enable webhooks |
| `hooks.mappings` | `[]` | Hook route mappings |

### RBAC & Infrastructure

| Value | Default | Description |
|-------|---------|-------------|
| `rbac.clusterAdmin.enabled` | `false` | Bind cluster-admin role |
| `rbac.clusterReadOnly.enabled` | `false` | Bind the built-in `view` ClusterRole for cluster-wide read-only access (skipped when `clusterAdmin` is enabled) |
| `rbac.orchestrator.enabled` | `false` | Scoped cross-namespace orchestrator ClusterRole (skipped when `clusterAdmin` is enabled) |
| `infraTools.enabled` | `false` | Install kubectl, flux, sops, age |
| `infraTools.kubeconfigs.existingSecret` | `""` | Secret with kubeconfig files |

### Persistence

| Value | Default | Description |
|-------|---------|-------------|
| `persistence.enabled` | `false` | Create PVC (opt-in) |
| `persistence.size` | `10Gi` | Storage size |
| `persistence.storageClass` | `""` | Storage class (empty = default) |
| `persistence.existingClaim` | `""` | Use an existing PVC instead of creating one |

### Resources

| Value | Default | Description |
|-------|---------|-------------|
| `resources.requests.memory` | `512Mi` | Memory request |
| `resources.requests.cpu` | `250m` | CPU request |
| `resources.limits.memory` | `3Gi` | Memory limit |
| `resources.limits.cpu` | `2000m` | CPU limit |

### Workflows

| Value | Default | Description |
|-------|---------|-------------|
| `workflowDefaults.timeout` | `900` | Default step timeout (seconds) |
| `workflowDefaults.gitSync` | `true` | Pull repos before running |
| `workflowDefaults.concurrencyPolicy` | `Forbid` | CronJob concurrency |

### Advanced

| Value | Default | Description |
|-------|---------|-------------|
| `configOverlay` | `{}` | **Additive** overlay deep-merged onto the generated `openclaw.json`. Set or override individual keys while keeping everything the chart generates. Nested maps merge key-by-key; lists are replaced wholesale |
| `rawConfig` | `{}` | Full `openclaw.json` **replacement** (bypasses templating entirely). Prefer `configOverlay` — reach for this only to author the config from scratch. Setting both fails the render |
| `extraConfigMaps` | `[]` | Additional ConfigMaps: `[{name, mountPath, data}]` |
| `extraVolumes` | `[]` | Extra pod volumes |
| `extraVolumeMounts` | `[]` | Extra container volume mounts |
| `extraEnv` | `[]` | Extra environment variables |

### Expected Secret Keys

All optional — include only what your agent needs:

| Key | Purpose |
|-----|---------|
| `MATRIX_ACCESS_TOKEN` | Matrix bot token |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `DISCORD_BOT_TOKEN` | Discord bot token (read via env token source, not jq-injected) |
| `HOOKS_TOKEN` | Webhook auth (a distinct gateway auth token is derived from it) |
| `GITHUB_TOKEN` | GitHub API access |
| `BRAVE_API_KEY` | Brave web search |
| `ANTHROPIC_API_KEY` | Claude API key |
| `OPENROUTER_API_KEY` | OpenRouter key (when `agent.auth.provider: openrouter`) |
| `git-ssh-key` | SSH key for git repos |
| `claude-credentials.json` | Claude OAuth credentials |

Snapshot credentials go in `snapshots.credentials.existingSecret` (or the main secret): `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `SNAPSHOT_ENCRYPTION_PASSWORD` when encryption is on.

## Service Discovery

Agents are reachable within the cluster at:

```
{name}-devpod.devpod-{name}.svc.cluster.local:18789   # gateway
{name}-devpod.devpod-{name}.svc.cluster.local:18790   # skills API (JSON skill/command listing)
```

## Development

```bash
# Install test plugin
helm plugin install https://github.com/helm-unittest/helm-unittest.git

# Run tests (183 tests, 19 suites)
make test

# Runtime tests: extracts the rendered startup script and executes it
# under sh against fixtures (skill prune + config-revert detection).
# Needs helm, jq, and python3 with PyYAML.
make test-shell

# Lint
make lint

# Template an example
make template

# Template all examples
make template-all
```

## Troubleshooting

```bash
# Pod not starting — check events and startup logs
kubectl describe pod -n devpod-{name} -l app.kubernetes.io/instance={name}
kubectl logs -n devpod-{name} deployment/{name}-devpod -f

# Workflow not running — check CronJob and trigger manually
kubectl get cronjobs -n devpod-{name}
kubectl create job -n devpod-{name} "test-$(date +%s)" --from=cronjob/{name}-wf-{workflow}

# Secret missing
kubectl get secret -n devpod-{name} devpod-secrets

# Config silently reverted — `openclaw doctor --fix` rejected the generated
# config and fell back to openclaw.json.last-good. Look for the banner in the
# logs, or check the sentinel:
kubectl exec -n devpod-{name} deployment/{name}-devpod -- cat /root/.openclaw/.config-reverted
kubectl logs -n devpod-{name} deployment/{name}-devpod | grep config_revert

# Gateway never binds :18789 on a hardened agent — usually the npm update check
# hanging with no route out. Confirm config.updateCheckOnStart is false, or
# allowlist registry.npmjs.org in networkPolicy.egress.fqdns.

# Auto-pull not picking up commits (it skips dirty trees by design)
kubectl exec -n devpod-{name} deployment/{name}-devpod -- tail -f /tmp/git-sync.log
```

## License

[MIT](LICENSE)
