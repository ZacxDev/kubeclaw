# KubeClaw

Helm chart for deploying OpenClaw AI agent devpods on Kubernetes.

## Repository Structure

```
kubeclaw/
├── Chart.yaml              # Chart metadata (v0.2.22)
├── values.yaml             # All configurable values with defaults
├── templates/              # Helm templates (24 files)
│   ├── _helpers.tpl        # Template helper functions (naming, labels, defaults)
│   ├── deployment.yaml     # Agent pod (startup script, volumes, probes)
│   ├── configmap.yaml      # Generated openclaw.json + repos.json
│   ├── configmap-skills.yaml        # Skill markdown files
│   ├── configmap-extra.yaml         # Extra ConfigMaps (e.g. agent registry)
│   ├── configmap-email-plugin.yaml  # Email channel plugin configuration
│   ├── configmap-workspace.yaml     # Workspace files URLs/metadata
│   ├── configmap-workspace-content.yaml  # Workspace inline content files
│   ├── configmap-workflow-skills.yaml    # Inline step skills per workflow
│   ├── cronjob-workflow.yaml        # CronJob per workflow definition
│   ├── cronjob-snapshot.yaml         # CronJob for scheduled workspace snapshots
│   ├── cronjob-email-poller.yaml    # CronJob for polling email via Mailpit
│   ├── clusterrole-orchestrator.yaml    # Scoped cross-namespace RBAC
│   ├── service.yaml        # ClusterIP on port 18789
│   ├── pvc.yaml            # PersistentVolumeClaim
│   ├── namespace.yaml      # Namespace (devpod-{name})
│   ├── serviceaccount.yaml          # Pod ServiceAccount
│   ├── role.yaml            # Namespace reader Role
│   ├── rolebinding.yaml     # RoleBinding
│   ├── clusterrolebinding.yaml      # Optional cluster-admin binding
│   ├── serviceaccount-workflow.yaml # Workflow pod ServiceAccount
│   ├── role-workflow.yaml           # Workflow exec permission Role
│   ├── rolebinding-workflow.yaml    # Workflow RoleBinding
│   └── NOTES.txt            # Post-install output
├── tests/                   # 141 helm-unittest tests (16 files)
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
├── Makefile                 # lint, test, template, template-all, clean
└── .helmignore              # Excludes .claude/, examples/, docs/, images from chart packaging
```

## How the Chart Works

### Resource Generation

Every agent deployment creates:
- **Namespace** `devpod-{agentName}`
- **Deployment** `{agentName}-devpod` with inline startup script
- **Service** `{agentName}-devpod` (ClusterIP, port 18789)
- **PVC** `{agentName}-data` (10Gi default, persistence disabled by default)
- **ConfigMap** `{agentName}-config` — templated `openclaw.json` + `repos.json`
- **ConfigMap** `{agentName}-skills` — skill `.md` files (if `skills` is defined)
- **ServiceAccount** + **Role** + **RoleBinding** — namespace reader

Optional resources:
- **ClusterRoleBinding** to cluster-admin (when `rbac.clusterAdmin.enabled: true`)
- **ClusterRole + ClusterRoleBinding** for orchestrator (when `rbac.orchestrator.enabled: true` and `clusterAdmin` is disabled)
- **CronJob** per workflow (when `workflows` is defined)
- **CronJob** for email polling (when `channels.email` is configured)
- **CronJob** for workspace snapshots (when `snapshots.enabled: true`)
- **ConfigMap** per workflow with inline step skills
- **ConfigMap** for email plugin (when `channels.email` is configured)
- **ConfigMap** for workspace files/content (when `workspaceFiles` or `workspaceContent` is defined)
- **ServiceAccount** + **Role** + **RoleBinding** shared across workflows and snapshots

### Startup Script (deployment.yaml)

The deployment runs a shell script that executes in order:

1. **SSH setup** — copies `git-ssh-key` from secret to `/root/.ssh/id_rsa`
2. **Repo clone/pull** — iterates `repos.json`, clones new repos or pulls existing
3. **Persist ~/.openclaw** — symlinks to `/data/openclaw` so sessions/cron state survive restarts
4. **Email plugin** (conditional) — installs email channel extension
5. **Skills** — copies `/config/skills/*.md` to `/root/.openclaw/skills/`
6. **Workspace files** — downloads URL-based files and copies inline content to workspace
7. **OAuth credentials** — copies `claude-credentials.json` from secret to PVC (first boot only), symlinks `/root/.claude` to `/data/.claude`
8. **Infrastructure tools** (conditional) — downloads kubectl, flux, sops, age; sets up in-cluster kubeconfig; mounts remote kubeconfigs
9. **Snapshot tools** (conditional) — downloads rclone, generates config, writes save script, restores from latest snapshot
10. **Secret injection** — uses `jq` to merge `MATRIX_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `HOOKS_TOKEN` into `openclaw.json` at runtime
11. **Auth bootstrap** — creates agent auth-profiles from Claude credentials
12. **Channel init** — runs `openclaw doctor --fix`
13. **Gateway loop** — starts `openclaw gateway --bind lan` with restart-on-failure

When `snapshots.save.onShutdown` is enabled, a **preStop lifecycle hook** calls `/usr/local/bin/snapshot-save` and `terminationGracePeriodSeconds` is extended (default 300s) to allow the snapshot to complete.

### Config Generation (configmap.yaml)

The chart templates `openclaw.json` from values unless `rawConfig` is set (which bypasses templating entirely). Secret fields are **not** in the ConfigMap — they're injected via `jq` at container startup from environment variables sourced from the Secret.

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
image:
  repository: your-registry/openclaw       # container image
  tag: latest
existingSecret: ""                         # Secret with tokens/keys
git:
  repos: []                                # [{url, path, branch}]
channels:
  matrix:
    homeserver: "https://matrix.example.com"
  email:                                   # email channel (Mailpit-based)
    address: ""
    mailpitUrl: ""
    portalUrl: ""
skills: {}                                 # filename.md: content
workspaceFiles: []                         # [{path, url}] downloaded at startup
workspaceContent: {}                       # path: inline content
agent:
  model:
    primary: "anthropic/claude-sonnet-4"
```

### Secret Keys (all optional)

`MATRIX_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `HOOKS_TOKEN`, `GITHUB_TOKEN`, `BRAVE_API_KEY`, `ANTHROPIC_API_KEY`, `git-ssh-key`, `claude-credentials.json`

Snapshot credentials (in `snapshots.credentials.existingSecret` or main secret):
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `SNAPSHOT_ENCRYPTION_PASSWORD`

### Agent Variants

- **Standard**: Default. Git repos, skills, Matrix/Telegram.
- **Coordinator**: Add `extraConfigMaps` with agent registry for multi-agent routing.
- **Orchestrator**: Set `rbac.orchestrator.enabled: true` and `infraTools.enabled: true` for scoped cross-namespace access to pods, cronjobs, jobs, and HelmReleases without full cluster-admin.
- **Infrastructure**: Set `infraTools.enabled: true` and `rbac.clusterAdmin.enabled: true` for kubectl/flux/sops access with cluster-admin RBAC.

### RBAC Tiers

Three-tier RBAC model:
1. **Namespace reader** (default): Read pods, logs, services, configmaps in own namespace
2. **Orchestrator** (`rbac.orchestrator.enabled: true`): Cross-namespace read for pods, logs, cronjobs, jobs, HelmReleases; exec and job create. Skipped when clusterAdmin is enabled (superset).
3. **Cluster admin** (`rbac.clusterAdmin.enabled: true`): Full cluster-admin via ClusterRoleBinding

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
make lint          # helm lint
make test          # 141 helm-unittest tests
make template      # render standard example
make template-all  # render all examples
```

### Testing

Tests are in `tests/` using helm-unittest. Install with:
```bash
helm plugin install https://github.com/helm-unittest/helm-unittest.git
```

Test files cover: deployment (21), snapshot (20), orchestrator-rbac (15), rbac (12), configmap (8), workflow cronjobs (18), workflow configmaps (8), workflow rbac (8), pvc (5), workspace-content (5), workspace (5), skills (4), namespace (3), service (3), extra configmaps (3), notes (3).

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
4. Add tests in the corresponding `tests/*_test.yaml`
5. Update `ci/full-values.yaml` if the value affects rendering

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

Agents deployed with this chart are reachable at:
```
{name}-devpod.devpod-{name}.svc.cluster.local:18789
```
