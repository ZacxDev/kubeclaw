# KubeClaw

Helm chart for deploying OpenClaw AI agent devpods on Kubernetes.

## Repository Structure

```
kubeclaw/
├── Chart.yaml              # Chart metadata (v0.7.1)
├── CHANGELOG.md            # Keep-a-Changelog history + per-release upgrade notes
├── values.yaml             # All configurable values with defaults
├── templates/              # Helm templates (28 files)
│   ├── _helpers.tpl        # Template helper functions (naming, labels, defaults)
│   ├── deployment.yaml     # Agent pod (startup script, volumes, probes, log sidecars)
│   ├── configmap.yaml      # Generated openclaw.json + repos.json
│   ├── configmap-skills.yaml        # Skill markdown files
│   ├── configmap-extra.yaml         # Extra ConfigMaps (e.g. agent registry)
│   ├── configmap-email-plugin.yaml  # Email channel plugin configuration
│   ├── configmap-workspace.yaml     # Workspace files URLs/metadata
│   ├── configmap-workspace-content.yaml  # Workspace inline content files
│   ├── configmap-workflow-skills.yaml    # Inline step skills per workflow
│   ├── configmap-clank-task-cli.yaml     # clank-task CLI binary (from bin/)
│   ├── configmap-clank-task-mcp.yaml     # clank-task-mcp stdio server binary (from bin/)
│   ├── cronjob-workflow.yaml        # CronJob per workflow definition
│   ├── cronjob-snapshot.yaml         # CronJob for scheduled workspace snapshots
│   ├── cronjob-email-poller.yaml    # CronJob for polling email via Mailpit
│   ├── networkpolicy.yaml           # Egress CiliumNetworkPolicy (opt-in)
│   ├── clusterrole-orchestrator.yaml    # Scoped cross-namespace RBAC
│   ├── service.yaml        # ClusterIP on ports 18789 (gateway) + 18790 (skills API)
│   ├── pvc.yaml            # PersistentVolumeClaim
│   ├── namespace.yaml      # Namespace (devpod-{name})
│   ├── serviceaccount.yaml          # Pod ServiceAccount
│   ├── role.yaml            # Namespace reader Role
│   ├── rolebinding.yaml     # RoleBinding
│   ├── clusterrolebinding.yaml      # Optional cluster-admin binding
│   ├── clusterrolebinding-readonly.yaml  # Optional cluster "view" binding
│   ├── serviceaccount-workflow.yaml # Workflow pod ServiceAccount
│   ├── role-workflow.yaml           # Workflow exec permission Role
│   ├── rolebinding-workflow.yaml    # Workflow RoleBinding
│   └── NOTES.txt            # Post-install output
├── bin/                     # Binaries shipped to agent pods via ConfigMap
│   ├── clank-task           # CLI for typed task operations
│   └── clank-task-mcp       # stdio MCP server (registered with OpenClaw)
├── plugins/
│   └── email/               # Email channel plugin (Node.js, index.js + plugin manifest)
├── tests/                   # 189 helm-unittest tests (19 files)
│   └── shell/               # Runtime tests: extracts the rendered startup script
│       ├── run.sh           #   and executes it under sh against fixtures
│       └── extract_block.py
├── examples/                # Complete deployment examples
│   ├── standard.yaml        # Minimal agent
│   ├── coordinator.yaml     # Multi-agent coordinator
│   ├── infrastructure.yaml  # Cluster admin agent
│   ├── workflow-product-iteration.yaml  # 3-step pipeline
│   └── workflow-stock-news.yaml         # Single-step daily workflow
├── docs/
│   └── migration-from-cronjobs.md    # CronJob migration guide
├── ci/                      # CI test values
│   ├── test-values.yaml
│   └── full-values.yaml
├── Makefile                 # lint, test, test-shell, template, template-all, clean
└── .helmignore              # Excludes .claude/, examples/, docs/, images from chart packaging
```

## How the Chart Works

### Resource Generation

Every agent deployment creates:
- **Namespace** `devpod-{agentName}`
- **Deployment** `{agentName}-devpod` with inline startup script
- **Service** `{agentName}-devpod` (ClusterIP; port 18789 gateway, 18790 skills API)
- **PVC** `{agentName}-data` (10Gi default, persistence disabled by default)
- **ConfigMap** `{agentName}-config` — templated `openclaw.json` + `repos.json`
- **ConfigMap** `{agentName}-skills` — skill `.md` files (if `skills` is defined)
- **ConfigMap** `{agentName}-clank-task-cli` + `-clank-task-mcp` — binaries shipped from `bin/` (when `mcpServers.clankTask.enabled`, default **false**)
- **ServiceAccount** `{agentName}-devpod` + **Role/RoleBinding** `{agentName}-reader` — namespace reader

Optional resources:
- **ClusterRoleBinding** `{agentName}-devpod-admin` to cluster-admin (when `rbac.clusterAdmin.enabled: true`)
- **ClusterRoleBinding** `{agentName}-view` to the built-in `view` ClusterRole (when `rbac.clusterReadOnly.enabled: true` and `clusterAdmin` is disabled)
- **ClusterRole + ClusterRoleBinding** `{agentName}-orchestrator` (when `rbac.orchestrator.enabled: true` and `clusterAdmin` is disabled)
- **CiliumNetworkPolicy** `{agentName}-egress` (when `networkPolicy.enabled: true`)
- **CronJob** per workflow (when `workflows` is defined)
- **CronJob** for email polling (when `channels.email` is configured)
- **CronJob** for workspace snapshots (when `snapshots.enabled: true`)
- **ConfigMap** per workflow with inline step skills
- **ConfigMap** for email plugin (when `channels.email` is configured)
- **ConfigMap** for workspace files/content (when `workspaceFiles` or `workspaceContent` is defined)
- **ServiceAccount** `{agentName}-workflow` + **Role** `{agentName}-workflow-exec` + **RoleBinding** shared across workflows and snapshots
- **Log-shipping sidecars** on the agent pod (when `logShipping.enabled: true`)

### Startup Script (deployment.yaml)

The deployment runs a shell script that executes in order:

1. **SSH setup** — copies `git-ssh-key` from secret to `/root/.ssh/id_rsa`
2. **Repo clone/pull** — iterates `repos.json`, clones new repos or pulls existing
3. **Background git auto-pull** (conditional, `git.autoPull.enabled`, default true) — backgrounded loop that fetches repos every `intervalSeconds` (default 300). Skips dirty working trees, only pulls when origin has advanced, logs to `/tmp/git-sync.log` and `/proc/1/fd/{1,2}` so messages reach `kubectl logs`.
4. **Persist `~/.openclaw`** — `/root/.openclaw` is the data PVC mounted at `subPath: openclaw`, so sessions/cron state survive restarts (the script only `mkdir -p`s it)
5. **Email plugin** (conditional) — copies the extension into openclaw's stock `dist/extensions/email` dir (the pre-2026.6 `node_modules/openclaw/extensions/` location is rejected with "extension entry escapes package directory")
6. **OAuth credentials** — copies `claude-credentials.json` from secret to PVC (first boot only), symlinks `/root/.claude` to `/data/.claude`
7. **Infrastructure tools** (conditional) — downloads kubectl, flux, sops, age; sets up in-cluster kubeconfig; mounts remote kubeconfigs
8. **Snapshot tools** (conditional) — downloads rclone (skipped if already installed in the image), generates config, writes save script
9. **Snapshot restore** (conditional) — restores from latest snapshot before skill/workspace copies run
10. **Skills** — copies each `/config/skills/<key>.md` to `/root/.openclaw/skills/<key>/SKILL.md`, where `<key>` is the `skills:` map key (the filename stem via `basename "$f" .md`), NOT the frontmatter `name:` field (runs AFTER snapshot restore so ConfigMap skills are authoritative)
11. **Skill prune** (conditional, `pruneStaleSkills`, default false) — a manifest at `/data/.chart-skills-manifest` (outside the skills tree, immune to snapshot restore) records the chart-managed skill dirs; on a later boot, dirs in the previous manifest that are no longer in values AND have a `SKILL.md` are deleted. Unmanaged / snapshot-restored / agent-authored skills are never touched. First boot prunes nothing (empty manifest), then writes the manifest — so removals take effect on the NEXT restart. Covered by `make test-shell`.
12. **Workspace files** — downloads URL-based files into the workspace (runs AFTER snapshot restore)
13. **Workspace content** — writes inline `workspaceContent` files (runs AFTER snapshot restore)
14. **WhatsApp Baileys credentials persist** (conditional) — symlinks credential store onto PVC
15. **Secret injection** — uses `jq` to merge `MATRIX_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `HOOKS_TOKEN` into `openclaw.json` at runtime (Discord uses an env-source token, no jq injection). Also derives a gateway auth token distinct from `HOOKS_TOKEN` (gateway v2026.3+ requires `hooks.token != gateway.auth.token`).
16. **Telegram pre-approval** — writes pre-approved Telegram user IDs
17. **Channel init + config-revert detection** — runs `openclaw doctor --fix`, then (unless `config.onRevert: ignore`) checks that the chart's intended scalars from `/config/openclaw.json` (`agents.defaults.model.primary`, `workspace`, `maxConcurrent`, `agents.list[0].id`) still match the active `openclaw.json`. Detection is semantic (not a file hash) because doctor legitimately mutates a valid config too. A mismatch means doctor silently reverted to `openclaw.json.last-good`; emits a banner + structured `event=config_revert` JSON line + a `/root/.openclaw/.config-reverted` sentinel. `warn` (default) continues; `fail` exits 1 (CrashLoopBackOff). Runs BEFORE the channel strip.
18. **Channel strip** — removes channel blocks not explicitly enabled in values
19. **Auth bootstrap** — writes `agents/<id>/agent/auth-profiles.json` (and `agents/main/agent/`). Two mutually exclusive branches selected by `agent.auth.provider`: an **OAuth** profile from `claude-credentials.json` (`anthropic-oauth`, default), or an **api_key** profile from an env var (`openrouter` / `apikey`).
20. **Extra init commands** — runs `extraInitCommands` shell snippet
21. **Workspace sync** (background; runs only when both `$PORTAL_URL` and `$HOOKS_TOKEN` are set) — 2-way `/data/workspace` ↔ portal S3 sync: initial pull, 15s upload cycle (text files only, 5-min grace on recently-touched files), deletion reconciliation every ~10 cycles. Sends `X-Sync-Source: workspace-sync` so the portal doesn't write back and create an mtime loop.
22. **Skills API endpoint** (background, always) — small Python HTTP server on port **18790** that reads skill/command frontmatter and serves it as JSON
23. **Gateway loop** — starts `openclaw gateway --bind lan` with restart-on-failure

When `snapshots.save.onShutdown` is enabled, a **preStop lifecycle hook** calls `/usr/local/bin/snapshot-save` and `terminationGracePeriodSeconds` is extended (default 300s) to allow the snapshot to complete.

The `clank-task` CLI and `clank-task-mcp` stdio server are mounted from ConfigMaps to `/usr/local/bin/` and made executable. When `mcpServers.clankTask.enabled` is true (**default false**), `clank-task-mcp` is registered in `openclaw.json` under the native `mcp.servers."clank-task"` key and runs as a stdio child process of the agent for typed task tool calls. The key matters: the chart historically emitted a top-level `mcpServers` key, which both openclaw 2026.6.1 and 2026.7.x reject with `<root>: Invalid input`. The stdio `transport` field is deliberately omitted — 2026.6.1's schema only allows `sse`/`streamable-http` and infers stdio from `command`, while 2026.7.x also accepts an explicit `stdio`; omitting it works on both.

When `logShipping.enabled: true`, three busybox sidecars tail agent output to stdout for cluster log collection (e.g. Grafana Alloy → Loki):

| Sidecar | Tails |
|---------|-------|
| `openclaw-log-tailer` | `/tmp/openclaw/*.log` |
| `stability-bundle-tailer` | `/root/.openclaw/logs/stability/` bundles, each emitted as a single JSON stdout line |
| `trajectory-tailer` | Per-session JSONL trajectories; emits `model.completed` lines in an event envelope, watermarked by `basename#mtime` |

### Config Generation (configmap.yaml)

The chart templates `openclaw.json` from values. Secret fields are **not** in the ConfigMap — they're injected via `jq` at container startup from environment variables sourced from the Secret.

Three mutually exclusive paths, in `templates/configmap.yaml`:

| Values | Path | Result |
|--------|------|--------|
| neither set | verbatim text | The generated config, emitted byte-for-byte as the template writes it |
| `rawConfig` set | `toJson` | The `rawConfig` values replace everything; no generation at all |
| `configOverlay` set | `mustFromJson` → `mergeOverwrite` → `toJson` | Generated config with the overlay deep-merged on top (compact JSON) |
| **both** set | `fail` | Render aborts — ambiguous, so it fails loudly |

(Listed in evaluation order — `rawConfig` is tested first.)

The generated JSON lives in a `kubeclaw.configJson` named template so all three paths can consume it. Two things about that block are load-bearing:

- **The no-overlay path emits the text verbatim** rather than round-tripping through `fromJson`/`toJson`. Round-tripping would reformat and reorder keys, changing the ConfigMap bytes, changing `checksum/config`, and rolling-restarting every agent in the fleet for a semantically identical config.
- **The `define`'s closing `{{- end -}}` must keep its trailing dash.** `checksum/config` hashes this template's *entire* rendered output, so a stray leading newline has the same fleet-restart effect. **`make render-diff` does NOT catch this** — dropping the dash leaves it at 10/10 identical because the ConfigMap *document* is unchanged; only the `include`-based checksum moves. **`make byte-diff` does catch it** (verified by mutation). Run both.

The overlay path parses the generated text with **`mustFromJson`**, so a malformed conditional in the JSON block fails the render — but only when an overlay is in use. The `must` prefix is load-bearing: plain `fromJson` returns `{"Error": "<msg>"}` and lets the render *succeed*, silently swapping the entire config for an error map. That map is valid JSON, so the startup script's `jq` passes and the agent boots with no model, workspace or channels.

**`configOverlay` cannot add an unmodelled channel.** The startup script's channel strip (`deployment.yaml`) builds its allowlist from Helm values only and `jq`-deletes every other `.channels.*` key, so an overlay-declared channel renders into the ConfigMap and is then removed at boot with no error. Adding a channel requires a first-class value plus an entry in the strip list.

### Workflow CronJobs (cronjob-workflow.yaml)

Each workflow creates a CronJob that:
1. Discovers the agent pod by label `app.kubernetes.io/instance={agentName}`
2. Optionally git-syncs all repos via `kubectl exec`
3. Runs steps sequentially — each gets a unique session ID
4. Inline skills come from a ConfigMap volume; `skillRef` skills are read from the agent pod filesystem via `kubectl exec`
5. Context variables (`OUTPUT_DIR`, `REPORT_PATH`, `DATE`, `WORKFLOW`, `STEP`, custom) are prepended to each skill message
6. Step output is saved to `$OUTPUT_DIR/{step}.txt`
7. Optional: commit report via git, send Telegram notifications

### Template Helpers (_helpers.tpl)

| Helper | Returns |
|--------|---------|
| `kubeclaw.fullname` | `{agentName}` (truncated 63 chars) |
| `kubeclaw.namespace` | `devpod-{agentName}` |
| `kubeclaw.displayName` | `{agentDisplayName}` or `{agentName} Dev` |
| `kubeclaw.agentId` | `{agent.id}` or `{agentName}` |
| `kubeclaw.workspace` | `{agent.workspace}` or first repo path or `/data/workspace` |
| `kubeclaw.mentionPatterns` | Custom patterns or `["@{name}", "{name}"]` |
| `kubeclaw.secretName` | `{existingSecret}` or `{agentName}-secrets` |
| `kubeclaw.pvcName` | `{persistence.existingClaim}` or `{agentName}-data` |
| `kubeclaw.hasWorkflows` | `true` if `workflows` has entries |
| `kubeclaw.workflowSaName` | `{agentName}-workflow` |
| `kubeclaw.workflowAgentId` | Workflow `agent` override or chart default |
| `kubeclaw.labels` | Standard Helm labels |
| `kubeclaw.chart` | `{chartName}-{chartVersion}` for labels |
| `kubeclaw.selectorLabels` | `app.kubernetes.io/name: devpod`, `instance: {name}`, `component` |
| `kubeclaw.workflowLabels` | Labels with `component: workflow` |

## Key Values

Only `agentName` is required. See `values.yaml` for all options with comments.

### Most Commonly Set

```yaml
agentName: ""                              # REQUIRED — drives all naming
replicaCount: 1                            # 0 = provision everything but don't run the pod ("paused" agent)
image:
  repository: your-registry/openclaw       # container image
  tag: latest
existingSecret: ""                         # Secret with tokens/keys
git:
  repos: []                                # [{url, path, branch}]
  autoPull:
    enabled: true                          # background fetch+pull loop
    intervalSeconds: 300
agent:
  model:
    primary: "anthropic/claude-sonnet-4"
  thinkingDefault: ""                      # off|minimal|low|medium|high; "" = model default
  defaults: {}                             # extra keys merged verbatim into agents.defaults
  auth:
    provider: "anthropic-oauth"            # anthropic-oauth | openrouter | apikey
    providerName: ""                       # api_key modes; defaults to "openrouter" for openrouter
    profileId: ""                          # defaults to "<providerName>:default"
    apiKeyEnv: ""                          # defaults to OPENROUTER_API_KEY / API_KEY
channels:
  matrix:
    enabled: false                         # DEFAULT OFF — see note below
    homeserver: "https://matrix.example.com"
  telegram: { enabled: false, allowFrom: [] }
  discord: { enabled: false, applicationId: "", dmPolicy: pairing, groupPolicy: allowlist, allowFrom: [] }  # native; token via DISCORD_BOT_TOKEN env source
  whatsapp: { enabled: false }             # Baileys-based; credentials persist on PVC
  teams: { enabled: false, appId: "", tenantId: "" }
  sms: { enabled: false, provider: twilio, phoneNumber: "" }
  email:                                   # email channel (Mailpit-based)
    enabled: false
    address: ""
    mailpitUrl: ""
    portalUrl: ""
config:
  onRevert: "warn"                         # warn|fail|ignore — surface silent openclaw.json.last-good reverts
  updateCheckOnStart: false                # emits update.checkOnStart; see note below
tools:
  web:
    search: { enabled: true, provider: brave, maxResults: 3 }
skills: {}                                 # filename.md: content
pruneStaleSkills: false                    # prune chart-managed skills removed from values (manifest-based, opt-in)
workspaceFiles: []                         # [{path, url}] downloaded at startup
workspaceContent: {}                       # path: inline content
mcpServers:
  clankTask:
    enabled: false                         # registers mcp.servers."clank-task" stdio server
gateway:
  http:
    endpoints:
      chatCompletions: { enabled: true }   # /v1/chat/completions
      responses: { enabled: true }         # /v1/responses (structured tool calls)
hooks:
  enabled: true
  allowedSessionKeyPrefixes: []            # empty emits the single prefix "hook:"
logShipping:
  enabled: false                           # busybox sidecars → stdout → Loki
```

**Two defaults that are OFF for compatibility reasons, not preference:**

- `channels.matrix.enabled: false` — openclaw 2026.6.x's matrix schema is `additionalProperties: false` and rejects the `streamMode` / `typingIndicator` / `dm.*` keys this chart emits, so a default-on matrix block makes the gateway refuse to start. Only enable on an openclaw build that accepts the emitted block.
- `config.updateCheckOnStart: false` — on openclaw ≥ 2026.6.11 the update check does a blocking per-plugin `registry.npmjs.org` fetch (~2.5s × ~49 stock plugins). For an agent whose egress does not allowlist the npm registry, the fetch has no route and hangs, so `openclaw doctor --fix` never completes, the gateway never binds `:18789`, and the pod CrashLoopBackOffs past its startupProbe budget. Set `true` only if you allowlist `registry.npmjs.org`.

### Secret Keys (all optional)

`MATRIX_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `DISCORD_BOT_TOKEN`, `HOOKS_TOKEN`, `GITHUB_TOKEN`, `BRAVE_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY` (when `agent.auth.provider: openrouter`), `git-ssh-key`, `claude-credentials.json`

Snapshot credentials (in `snapshots.credentials.existingSecret` or main secret):
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `SNAPSHOT_ENCRYPTION_PASSWORD`

### Agent Variants

- **Standard**: Default. Git repos, skills, and a chat channel (all channels default off — enable one explicitly).
- **Coordinator**: Add `extraConfigMaps` with agent registry for multi-agent routing.
- **Read-only diagnostic**: Set `rbac.clusterReadOnly.enabled: true` and `infraTools.enabled: true` for cluster-wide `kubectl get/describe/logs` with no write access.
- **Orchestrator**: Set `rbac.orchestrator.enabled: true` and `infraTools.enabled: true` for scoped cross-namespace access to pods, cronjobs, jobs, and HelmReleases without full cluster-admin.
- **Infrastructure**: Set `infraTools.enabled: true` and `rbac.clusterAdmin.enabled: true` for kubectl/flux/sops access with cluster-admin RBAC.

### RBAC Tiers

Four-tier RBAC model, each tier skipped when a superset tier is enabled:
1. **Namespace reader** (default): Read pods, logs, services, configmaps in own namespace
2. **Cluster read-only** (`rbac.clusterReadOnly.enabled: true`): Binds the agent SA to the built-in `view` ClusterRole for read-only access across all namespaces — covers the common diagnostic agent without hand-rolled RBAC. Skipped when clusterAdmin is enabled.
3. **Orchestrator** (`rbac.orchestrator.enabled: true`): Cross-namespace read for pods, logs, cronjobs, jobs, HelmReleases; exec and job create. Skipped when clusterAdmin is enabled.
4. **Cluster admin** (`rbac.clusterAdmin.enabled: true`): Full cluster-admin via ClusterRoleBinding

### Fleet Hardening

Three first-class hardening values (added in 0.7.0) replace the per-release `postRenderers` + hand-authored NetworkPolicy consumers used to need. **Every default is backward-compatible** — a default-values render differs from 0.6.0 only by the safe container `securityContext`; the generated `openclaw.json` is byte-identical.

| Value | Default | Notes |
|-------|---------|-------|
| `securityContext` | `allowPrivilegeEscalation: false` + `seccompProfile.type: RuntimeDefault` | Merged onto the `agent` container. To ship none (pre-0.7.0), set to `null` — an empty `{}` does **not** clear it, since Helm deep-merges maps. `capabilities.drop: ["ALL"]` is opt-in, **not** default: dropping caps removes CHOWN/DAC_OVERRIDE/FOWNER and breaks `apt-get install`/dpkg at init, so only use it on images with deps baked in. |
| `podSecurityContext` | `{}` (nothing rendered) | Do **not** set `runAsNonRoot`/`runAsUser` without reworking the image — the startup script hardcodes writes to `/root/.openclaw`, `/root/.ssh`, `/root/.kube` and `/usr/local/bin` (UID 0). |
| `tls.verify` | `false` | Drives `NODE_TLS_REJECT_UNAUTHORIZED` (`false` → `"0"`, verification OFF). This was previously hardcoded to `0`; the default preserves it so no agent breaks. Prefer flipping to `true` per-agent, and supply a CA via `NODE_EXTRA_CA_CERTS` (`extraEnv`) for internal self-signed endpoints. |
| `networkPolicy.enabled` | `false` | Renders an **egress-only** `CiliumNetworkPolicy` (ingress stays default-allow so probes and port-forwards keep working). |

NetworkPolicy specifics:
- `networkPolicy.cilium` must stay `true` — the allowlist uses `toFQDNs`, which a plain `networking.k8s.io` NetworkPolicy cannot express. Setting it `false` while enabled **fails the render** with a clear message.
- Enabling it with an empty allowlist (no `egress.fqdns`/`endpoints`/`entities`) also **fails the render**. A default-deny egress that only reaches DNS + apiserver bricks the agent while *looking* connected, because DNS still resolves. To intentionally allow all egress, leave `networkPolicy.enabled: false`.
- `matchName` is **exact-host**. `github.com` does not cover `api.github.com` (gh CLI) or `codeload.github.com` (git archive/clone) — list every host the agent actually uses.
- An fqdn entry containing `*` renders as a Cilium `matchPattern`; otherwise `matchName`. A raw selector map (`{matchName: "x"}`) is passed through as-is.

### Workflow Schema

```yaml
workflows:
  <name>:
    schedule: "cron"           # required
    timeout: 1800              # job deadline (seconds)
    agent: ""                  # agent ID override
    gitSync: true              # pull repos before running
    context:                   # env vars for steps
      KEY: "value"
    report:
      path: "path/{{workflow}}-{{date}}.md"
      commit: true
      branch: "trunk"
    notify:
      telegram:
        chatId: ""
    steps:
      - name: "step-name"     # required
        skill: |               # inline skill content
          Instructions...
        skillRef: ""           # OR: file path on agent pod
        timeout: 300
        notify: false          # send output to Telegram
```

### Snapshot Schema

```yaml
snapshots:
  enabled: false
  provider: s3                 # s3, minio, or r2
  bucket: ""                   # required
  prefix: ""                   # defaults to agentName
  endpoint: ""                 # required for minio/r2
  region: "us-east-1"
  paths:                       # directories to snapshot
    - /data/workspace
  exclude:                     # rclone glob patterns (--exclude)
    - ".git/objects/**"
    - "node_modules/**"
  excludeFrom: ""              # path to exclude file (--exclude-from)
  save:
    schedule: "0 */6 * * *"    # CronJob schedule
    onShutdown: true           # preStop hook snapshot
    terminationGracePeriodSeconds: 300
  restore:
    onStartup: true            # restore if not previously restored
  retention:
    maxCount: 5                # keep N newest, delete oldest on success
  encryption:
    enabled: false             # rclone crypt layer
  bandwidth:
    limit: "0"                 # rclone bwlimit for scheduled saves
  credentials:
    existingSecret: ""         # Secret with AWS_ACCESS_KEY_ID, etc.
    useIRSA: false             # use pod SA IAM role instead
```

S3 key structure: `s3://bucket/{prefix}/{timestamp}/{dirname}/...`

Scheduled saves run with `ionice -c3 nice -n 19` for low-priority I/O. Restore and shutdown saves run at full speed. Retention cleanup runs after each successful save, deleting the oldest snapshots beyond `maxCount`.

**Ignore patterns**: Place a `.snapshotignore` file in the snapshot path root (e.g., `/data/workspace/.snapshotignore`) with rclone exclude patterns (one per line). Automatically picked up during saves. Alternatively, set `excludeFrom` to a custom file path. The `exclude` list in values provides Helm-level defaults.

## Development

```bash
make lint           # helm lint
make test           # 189 helm-unittest tests
make test-shell     # runtime tests of the rendered startup script
make render-diff    # semantic diff of generated openclaw.json vs trunk
make byte-diff      # full-manifest byte diff vs trunk (version normalised)
make template       # render standard example
make template-all   # render all examples
make template-fleet # render the three-agent fleet example
```

### Testing

Three tiers — **all must be green**; they cover structurally different things.

**Tier 1 — `make test` (helm-unittest, 189 tests in 19 files).** Asserts on rendered template text. Install the plugin with:
```bash
helm plugin install https://github.com/helm-unittest/helm-unittest.git
```

| Suite | Tests | Suite | Tests |
|-------|------:|-------|------:|
| deployment | 31 | orchestrator-rbac | 15 |
| configmap | 22 | rbac | 15 |
| snapshot | 20 | workflow-configmap | 8 |
| workflow-cronjob | 18 | workflow-rbac | 8 |
| networkpolicy | 7 | securitycontext | 6 |
| configmap-workspace | 5 | configmap-workspace-content | 5 |
| pvc | 5 | configmap-skills | 4 |
| configmap-extra | 3 | namespace | 3 |
| notes | 3 | service | 3 |
| tls | 2 | | |

**Tier 2 — `make test-shell`.** helm-unittest can only assert on rendered *text*, so it cannot catch a logic bug in the inline startup script. This harness renders the chart, extracts the relevant script block (`tests/shell/extract_block.py`), rewrites the absolute roots (`/root/.openclaw`, `/data`, `/config/skills`) to a throwaway sandbox, and executes the **actual rendered logic** under `sh` against fixtures. It covers the two safety-critical behaviors:
- **Skill prune** — a chart-managed skill removed from values is pruned while an unmanaged/agent-authored one survives; first boot (no manifest) prunes nothing and then writes the manifest.
- **Config-revert detection** — `warn` on a revert emits banner + sentinel and exits 0; `fail` does the same and exits 1; a doctor run that *accepted* the config (mutating it but preserving the chart's scalars) stays silent. That last case is what broke the original file-hash approach and motivated the semantic check.

**Tier 3 — `make render-diff`.** Neither tier above can catch a change to config *generation* that keeps every assertion passing while altering what the agent actually runs. This renders the chart against all ten value files in the repo (`examples/`, `examples/fleet/`, `ci/`), extracts `data["openclaw.json"]`, parses it, and deep-compares against a git ref (`REF=`, default `trunk`).

Run it before/after **any** edit to `configmap.yaml` or `_helpers.tpl`.

The harness runs its own **negative control** first — it proves it can detect a one-nested-key difference, a missing key and a changed list length — and `compare` refuses to run until that has passed. A comparison tool that always reports "identical" is the default failure mode here, so the tool's verdict is worthless until it has been watched to fail.

Note it compares *semantics*. For a change that must also preserve *bytes* (anything affecting `checksum/config`, which rolling-restarts the fleet), additionally `sha256sum` the full rendered manifests against a `git archive` of the ref.

**`ci/overlay-values.yaml` is the only value file that exercises `configOverlay`**, so it is what makes both gates cover the *merge* rather than only proving the feature is inert when unused. Its `tools.web.search.enabled: false` is load-bearing and commented as such: it is the sole falsy override, and without one, `mergeOverwrite` and sprig's `merge` render byte-identically — a merge-semantics regression would survive. Mutation-verified: with it, all three of operand-swap / overlay-dropped / `merge`-instead-of-`mergeOverwrite` are caught; without it, the third survives.

Both gates treat a value file present on one side only as `NEW (not compared)` and a file that *vanished* as FATAL, so adding a value file does not redden CI while a deletion still fails loudly.

Requires `helm`, `jq`, and `python3` with PyYAML. On NixOS:
```bash
nix-shell -p kubernetes-helm jq "python3.withPackages(p: [p.pyyaml])" --run "make test-shell"
nix-shell -p kubernetes-helm "python3.withPackages(p: [p.pyyaml])" --run "make render-diff"
```

### Template Debugging

```bash
helm template test . -f examples/standard.yaml
helm template test . -f examples/workflow-product-iteration.yaml
```

## Common Patterns

### Adding a New Value

1. Add to `values.yaml` with a comment
2. Reference in the appropriate template (usually `configmap.yaml` or `deployment.yaml`)
3. Add to `_helpers.tpl` if it needs default-resolution logic
4. Add tests in the corresponding `tests/*_test.yaml` — and `tests/shell/run.sh` if it changes startup-script *logic* rather than rendered text
5. Update `ci/full-values.yaml` if the value affects rendering
6. Bump `Chart.yaml` `version` and add a `CHANGELOG.md` entry with **Upgrade notes** — consumers read those to know what to adopt

**Defaults must be backward-compatible.** Consumers upgrade by bumping a chart ref in Flux; a changed default silently changes every agent in the fleet. Prove it with a render diff against the previous version before shipping (that is how 0.7.0's "only the container securityContext changed, `openclaw.json` byte-identical" claim was established).

### Adding a New Template

1. Create `templates/{resource}.yaml`
2. Use `kubeclaw.namespace` for namespace, `kubeclaw.labels` for labels
3. Add conditional rendering if the resource is optional
4. Create `tests/{resource}_test.yaml` with test cases
5. Update `.helmignore` if new non-chart files are added

### Modifying the Startup Script

The startup script is inline in `templates/deployment.yaml` inside the container command. Changes to it trigger pod restarts because of the `checksum/config` annotation. Keep the script sequential — each section depends on the previous one completing.

### Modifying Workflow Orchestration

The workflow CronJob script is in `templates/cronjob-workflow.yaml`. It uses Go template range loops over `workflows` and `steps`. The script uses shell variables (`$POD`, `$STEP_OUTPUT`, etc.) alongside Helm template variables (`{{ $wfName }}`, `{{ $step.name }}`). When editing, distinguish between Helm-time rendering and shell-time execution.

## Deployment Context

This chart is consumed as a FluxCD GitRepository source. Consumers create a `GitRepository` pointing to this repo, then a `HelmRelease` per agent with inline values. The chart itself is never `helm install`ed directly in production — it's always rendered by Flux's Helm controller.

Known consumers (per `CHANGELOG.md`): the `datapacket-talos` hand-authored HelmReleases, ClawSail's Go value generator, and clawgate's vendored chart copy. Each release's **Upgrade notes** are written for them.

Agents deployed with this chart are reachable at:
```
{name}-devpod.devpod-{name}.svc.cluster.local:18789
```
