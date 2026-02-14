# KubeClaw

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Helm](https://img.shields.io/badge/Helm-v3-blue)](https://helm.sh)

A Helm chart for deploying [OpenClaw](https://github.com/ZacxDev/openclaw-image) AI agent devpods on Kubernetes.

Reduces deploying a new agent from ~8 files across 3 directories to **2 files**: a HelmRelease values file + a SOPS-encrypted secret.

## What is this?

KubeClaw deploys **OpenClaw agent pods** — long-running AI agents that connect to Matrix/Telegram, clone git repos, execute skills, and run scheduled workflows. Each agent gets its own namespace, persistent storage, RBAC, and service.

**Key features:**
- One-file agent deployment (all config in HelmRelease values)
- Three agent variants: standard, coordinator, infrastructure
- Workflow orchestration — multi-step scheduled pipelines via CronJobs
- Built-in Telegram notifications, git report commits, and inter-step data passing
- FluxCD-native with SOPS secret encryption

## Prerequisites

- Kubernetes 1.27+
- Helm 3.x
- An OpenClaw container image (see [openclaw-image](https://github.com/ZacxDev/openclaw-image) for building your own)
- SOPS + Age for secret encryption (optional, for FluxCD)
- `helm-unittest` plugin for running tests (optional, for development)

## Quick Start

```bash
# Set your image in values or override at install time
helm install myagent . -f examples/standard.yaml --set image.repository=your-registry/openclaw
```

## Usage with FluxCD

```yaml
# GitRepository source
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: kubeclaw
  namespace: flux-system
spec:
  url: ssh://git@github.com/ZacxDev/kubeclaw.git
  ref:
    branch: main
  secretRef:
    name: flux-git-auth

---
# HelmRelease per agent
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: promptver-agent
  namespace: flux-system
spec:
  targetNamespace: devpod-promptver
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
    agentName: promptver
    # ... rest of values
```

## Agent Variants

| Variant | Example | Features |
|---------|---------|----------|
| **Standard** | `examples/standard.yaml` | Git repos, skills, Matrix bot |
| **Coordinator** | `examples/coordinator.yaml` | Extra configmaps (agents registry) |
| **Infrastructure** | `examples/infrastructure.yaml` | kubectl, flux, sops, cluster-admin RBAC |

## Architecture

The chart creates:
- **Namespace** `devpod-{agentName}` (optional)
- **Deployment** with startup script that clones repos, sets up SSH/credentials, injects secrets via `jq`, runs `openclaw gateway`
- **Service** (ClusterIP on port 18789)
- **PVC** for persistent data (`/data`)
- **ConfigMap** with `openclaw.json` and `repos.json`
- **ConfigMap** for skill `.md` files (if any)
- **ServiceAccount** + **Role/RoleBinding** (namespace reader)
- **ClusterRoleBinding** to cluster-admin (if `rbac.clusterAdmin.enabled`)

When workflows are defined, the chart also creates:
- **CronJob** per workflow (orchestration pod using `kubectl exec`)
- **ConfigMap** per workflow (inline step skills)
- **ServiceAccount** + **Role/RoleBinding** for pod exec (shared across all workflows)

Secret tokens (`MATRIX_ACCESS_TOKEN`, etc.) are injected at runtime via environment variables from the referenced Secret, then merged into `openclaw.json` by `jq` in the startup script.

## Values Reference

### Required

| Value | Description |
|-------|-------------|
| `agentName` | Agent identifier. Used for naming, namespace (`devpod-{name}`), and defaults |

### Agent Configuration

| Value | Default | Description |
|-------|---------|-------------|
| `agentDisplayName` | `"{agentName} Dev"` | Human-readable name in Matrix/config |
| `agent.id` | `agentName` | Agent ID in openclaw.json |
| `agent.workspace` | First repo path or `/data/workspace` | Working directory |
| `agent.model.primary` | `anthropic/claude-sonnet-4` | Claude model |
| `agent.maxConcurrent` | `4` | Max concurrent sessions |
| `agent.mentionPatterns` | `["@{name}", "{name}"]` | Matrix mention triggers |

### Git

| Value | Default | Description |
|-------|---------|-------------|
| `git.email` | `agent@devpod.local` | Git commit email |
| `git.name` | `DevPod Agent` | Git commit name |
| `git.repos` | `[]` | Repos to clone: `[{url, path, branch}]` |

### Skills

| Value | Default | Description |
|-------|---------|-------------|
| `skills` | `{}` | Map of `filename.md: content` mounted at `/config/skills/` |

### Channels

| Value | Default | Description |
|-------|---------|-------------|
| `channels.matrix.enabled` | `true` | Enable Matrix |
| `channels.matrix.homeserver` | `https://matrix.example.com` | Matrix server |
| `channels.telegram.enabled` | `false` | Enable Telegram |

### Gateway

| Value | Default | Description |
|-------|---------|-------------|
| `gateway.mode` | `local` | Gateway mode |
| `gateway.callbackUrl` | `""` | Main gateway URL for posting results |

### Hooks

| Value | Default | Description |
|-------|---------|-------------|
| `hooks.enabled` | `true` | Enable webhook hooks |
| `hooks.mappings` | `[]` | Custom hook mappings (auto-generates element hook if empty) |

### Secrets

| Value | Default | Description |
|-------|---------|-------------|
| `existingSecret` | `""` | Name of existing Secret with tokens/keys |

Expected secret keys: `MATRIX_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `HOOKS_TOKEN`, `GITHUB_TOKEN`, `BRAVE_API_KEY`, `ANTHROPIC_API_KEY`, `git-ssh-key`, `claude-credentials.json`

### RBAC

| Value | Default | Description |
|-------|---------|-------------|
| `rbac.create` | `true` | Create ServiceAccount, Role, RoleBinding |
| `rbac.clusterAdmin.enabled` | `false` | Bind cluster-admin ClusterRole |

### Infrastructure Tools

| Value | Default | Description |
|-------|---------|-------------|
| `infraTools.enabled` | `false` | Install kubectl, flux, sops, age at startup |
| `infraTools.kubeconfigs.existingSecret` | `""` | Secret with kubeconfig files |

### Extra Resources

| Value | Default | Description |
|-------|---------|-------------|
| `extraConfigMaps` | `[]` | Extra ConfigMaps: `[{name, mountPath, data}]` |
| `extraVolumes` | `[]` | Extra pod volumes |
| `extraVolumeMounts` | `[]` | Extra container volume mounts |
| `extraEnv` | `[]` | Extra environment variables |

### Persistence

| Value | Default | Description |
|-------|---------|-------------|
| `persistence.enabled` | `true` | Enable PVC |
| `persistence.existingClaim` | `""` | Use existing PVC |
| `persistence.storageClass` | `""` | Storage class (empty = default) |
| `persistence.size` | `10Gi` | PVC size |

### Resources

| Value | Default | Description |
|-------|---------|-------------|
| `resources.requests.memory` | `512Mi` | Memory request |
| `resources.requests.cpu` | `250m` | CPU request |
| `resources.limits.memory` | `2Gi` | Memory limit |
| `resources.limits.cpu` | `2000m` | CPU limit |

### Advanced

| Value | Default | Description |
|-------|---------|-------------|
| `rawConfig` | `{}` | Full openclaw.json override (bypasses templating) |
| `image.repository` | `your-registry/openclaw` | Container image |
| `image.tag` | `latest` | Image tag |

## Workflows

Workflows let you define multi-step agent pipelines that run on a schedule. Each workflow generates a CronJob that orchestrates sequential agent steps via `kubectl exec` into the running agent pod.

### Workflow Values

| Value | Default | Description |
|-------|---------|-------------|
| `workflowImage.repository` | `bitnami/kubectl` | CronJob container image |
| `workflowImage.tag` | `latest` | CronJob image tag |
| `workflowDefaults.timeout` | `900` | Default per-step timeout (seconds) |
| `workflowDefaults.concurrencyPolicy` | `Forbid` | Default CronJob concurrency |
| `workflowDefaults.suspend` | `false` | Default suspend state |
| `workflowDefaults.gitSync` | `true` | Pull repos before running |
| `workflowDefaults.resources` | `64Mi/50m req, 128Mi/200m lim` | CronJob pod resources |

### Workflow Schema

```yaml
workflows:
  <name>:
    schedule: "cron expression"         # required
    timeout: 1800                       # job deadline (seconds)
    agent: ""                           # agent ID (defaults to agentName)
    gitSync: true                       # pull repos before running
    concurrencyPolicy: Forbid
    suspend: false
    context:                            # key-value pairs injected as env vars
      PROJECT: "myproject"
    report:
      path: "path/{{workflow}}-{{date}}.md"  # report file path
      commit: true                      # auto git commit/push
      branch: "trunk"                   # target branch
      repo: ""                          # repo path (defaults to first git.repos)
    notify:
      telegram:
        chatId: ""                      # Telegram chat ID for notifications
    steps:
      - name: "step-name"              # required
        skill: |                        # inline skill content
          Agent instructions...
        skillRef: ""                    # OR: file path on agent pod
        timeout: 300                    # per-step timeout
        notify: false                   # send step output to Telegram
```

### Context Variables

Every step skill message is prepended with these variables:

| Variable | Description |
|----------|-------------|
| `$OUTPUT_DIR` | Shared temp directory for step outputs |
| `$REPORT_PATH` | Report file path (from `report.path`) |
| `$DATE` | Current date (YYYYMMDD) |
| `$WORKFLOW` | Workflow name |
| `$STEP` | Current step name |
| Custom `context:` keys | Any key-value pairs from `context:` |

### Step Execution

Steps run sequentially. Each step:
1. Gets a unique session ID (`{workflow}-{timestamp}-{step}`) to prevent context accumulation
2. Loads skill content from ConfigMap (inline) or agent filesystem (skillRef)
3. Prepends context variables to the skill message
4. Executes via `openclaw agent --session-id ... --message ... --timeout ...`
5. Saves output to `$OUTPUT_DIR/{step}.txt`
6. On failure: sends error notification (if Telegram configured) and exits

### Notifications

When `notify.telegram.chatId` is set:
- **Pod not found**: Sends failure notification
- **Step failure**: Sends failure notification with step name
- **Step `notify: true`**: Sends step output (with Markdown, falls back to plain text)
- **Completion**: Sends success notification

### Report Commit

When `report.commit: true`:
- Runs `git add` on the report path
- Only commits if there are staged changes (`git diff --cached --quiet`)
- Includes Co-Authored-By footer with agent identity
- Pushes to configured branch

### Examples

- `examples/workflow-product-iteration.yaml` — 3-step product intelligence pipeline
- `examples/workflow-stock-news.yaml` — Single-step daily stock summary
- See `docs/migration-from-cronjobs.md` for migrating existing CronJobs

## Service Discovery

Each agent is reachable at:
```
{agentName}-devpod.devpod-{agentName}.svc.cluster.local:18789
```

## Development

### Prerequisites

```bash
# Install helm-unittest plugin
helm plugin install https://github.com/helm-unittest/helm-unittest.git
```

### Makefile Targets

```bash
make lint          # Helm lint
make test          # Run all unit tests
make template      # Render standard example
make template-all  # Render all examples
make clean         # Remove generated files
```

### Running Tests

```bash
# Run all tests (90 tests across 12 files)
helm unittest .

# Run specific test suite
helm unittest -f tests/deployment_test.yaml .

# Template with values for debugging
helm template test . -f examples/standard.yaml
helm template test . -f examples/workflow-product-iteration.yaml
```

### Test Structure

| File | Tests | Coverage |
|------|-------|---------|
| `tests/deployment_test.yaml` | 15 | Image, resources, probes, volumes, conditionals |
| `tests/configmap_test.yaml` | 8 | openclaw.json generation, agent config |
| `tests/rbac_test.yaml` | 12 | SA, Role, RoleBinding, ClusterRoleBinding |
| `tests/pvc_test.yaml` | 5 | Persistence, storageClass, existingClaim |
| `tests/configmap-skills_test.yaml` | 4 | Skill file ConfigMap |
| `tests/configmap-extra_test.yaml` | 3 | Extra ConfigMaps |
| `tests/namespace_test.yaml` | 3 | Namespace creation |
| `tests/service_test.yaml` | 3 | Service port and selectors |
| `tests/notes_test.yaml` | 3 | Install notes output |
| `tests/workflow-cronjob_test.yaml` | 18 | CronJob rendering, scheduling, config |
| `tests/workflow-configmap_test.yaml` | 8 | Workflow skill ConfigMaps |
| `tests/workflow-rbac_test.yaml` | 8 | Workflow RBAC resources |

## Troubleshooting

### Agent pod not starting

```bash
# Check pod events
kubectl describe pod -n devpod-{agent} -l app.kubernetes.io/instance={agent}

# Check startup logs (startup script output)
kubectl logs -n devpod-{agent} deployment/{agent}-devpod -f
```

### Workflow CronJob not triggering

```bash
# Check CronJob status
kubectl get cronjobs -n devpod-{agent}

# Manually trigger a workflow
kubectl create job -n devpod-{agent} \
  "manual-$(date +%s)" \
  --from=cronjob/{agent}-wf-{workflow-name}

# Check job logs
kubectl logs -n devpod-{agent} job/manual-{id}
```

### Workflow fails at pod discovery

The workflow CronJob discovers the agent pod using the label `app.kubernetes.io/instance={agentName}`. Verify:

```bash
kubectl get pods -n devpod-{agent} -l app.kubernetes.io/instance={agent}
```

### Secret not found

Ensure the `existingSecret` exists in the target namespace:

```bash
kubectl get secret -n devpod-{agent} devpod-secrets
```

## License

[MIT](LICENSE)
