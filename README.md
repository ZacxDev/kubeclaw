<p align="center">
  <img src="logo.svg" alt="KubeClaw Logo" width="200">
</p>

<h1 align="center">KubeClaw</h1>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://helm.sh"><img src="https://img.shields.io/badge/Helm-v3-blue" alt="Helm"></a>
</p>

<p align="center">A Helm chart for deploying <a href="https://github.com/ZacxDev/openclaw-image">OpenClaw</a> AI agent pods on Kubernetes.</p>

Deploy an AI agent in **2 files** instead of 8+. KubeClaw handles the namespace, deployment, service, PVC, RBAC, config generation, and optional scheduled workflows — all from a single HelmRelease values file and a secret.

## How It Works

KubeClaw deploys an OpenClaw agent pod that:

1. Clones your git repos via SSH
2. Connects to Matrix and/or Telegram
3. Listens for messages and executes skills (markdown instruction files)
4. Optionally runs scheduled multi-step workflows via CronJobs

Each agent gets its own namespace (`devpod-{name}`), persistent storage, service account, and service endpoint.

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
      matrix:
        homeserver: "https://matrix.example.com"

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
  MATRIX_ACCESS_TOKEN: "syt_..."
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
| **Orchestrator** | Cross-namespace workflow management | `rbac.orchestrator.enabled: true`, `infraTools.enabled: true` |
| **Infrastructure** | Cluster admin with kubectl/flux/sops | `infraTools.enabled: true`, `rbac.clusterAdmin.enabled: true` |

See `examples/` for complete configurations of each variant.

## What Gets Created

For every agent:

| Resource | Name | Purpose |
|----------|------|---------|
| Namespace | `devpod-{name}` | Isolation |
| Deployment | `{name}-devpod` | Agent pod with startup script |
| Service | `{name}-devpod` | ClusterIP on port 18789 |
| PVC | `{name}-data` | Persistent storage (10Gi default) |
| ConfigMap | `{name}-config` | Generated `openclaw.json` + `repos.json` |
| ConfigMap | `{name}-skills` | Skill markdown files |
| ServiceAccount | `{name}-devpod` | Pod identity |
| Role + RoleBinding | `{name}-reader` | Namespace read access |

Optional resources:
- **ClusterRoleBinding** to cluster-admin (when `rbac.clusterAdmin.enabled: true`)
- **ClusterRole + ClusterRoleBinding** for orchestrator (when `rbac.orchestrator.enabled: true` and `clusterAdmin` is disabled)

When workflows are defined, adds per-workflow CronJob + shared workflow RBAC.

## Values Reference

### Core

| Value | Default | Description |
|-------|---------|-------------|
| `agentName` | **required** | Agent name, used for all resource naming |
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

### Git

| Value | Default | Description |
|-------|---------|-------------|
| `git.email` | `agent@devpod.local` | Commit author email |
| `git.name` | `DevPod Agent` | Commit author name |
| `git.repos` | `[]` | Repos to clone: `[{url, path, branch}]` |

### Channels

| Value | Default | Description |
|-------|---------|-------------|
| `channels.matrix.enabled` | `true` | Enable Matrix |
| `channels.matrix.homeserver` | `https://matrix.example.com` | Matrix server URL |
| `channels.telegram.enabled` | `false` | Enable Telegram |

### Skills

| Value | Default | Description |
|-------|---------|-------------|
| `skills` | `{}` | `filename.md: content` map, mounted at `/config/skills/` |

### Hooks

| Value | Default | Description |
|-------|---------|-------------|
| `hooks.enabled` | `true` | Enable webhooks |
| `hooks.mappings` | `[]` | Hook route mappings |

### RBAC & Infrastructure

| Value | Default | Description |
|-------|---------|-------------|
| `rbac.clusterAdmin.enabled` | `false` | Bind cluster-admin role |
| `rbac.orchestrator.enabled` | `false` | Scoped cross-namespace orchestrator ClusterRole |
| `infraTools.enabled` | `false` | Install kubectl, flux, sops, age |
| `infraTools.kubeconfigs.existingSecret` | `""` | Secret with kubeconfig files |

### Persistence

| Value | Default | Description |
|-------|---------|-------------|
| `persistence.enabled` | `true` | Create PVC |
| `persistence.size` | `10Gi` | Storage size |
| `persistence.storageClass` | `""` | Storage class (empty = default) |

### Resources

| Value | Default | Description |
|-------|---------|-------------|
| `resources.requests.memory` | `512Mi` | Memory request |
| `resources.requests.cpu` | `250m` | CPU request |
| `resources.limits.memory` | `2Gi` | Memory limit |
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
| `rawConfig` | `{}` | Full `openclaw.json` override (bypasses templating) |
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
| `HOOKS_TOKEN` | Webhook auth |
| `GITHUB_TOKEN` | GitHub API access |
| `BRAVE_API_KEY` | Brave web search |
| `ANTHROPIC_API_KEY` | Claude API key |
| `git-ssh-key` | SSH key for git repos |
| `claude-credentials.json` | Claude OAuth credentials |

## Service Discovery

Agents are reachable within the cluster at:

```
{name}-devpod.devpod-{name}.svc.cluster.local:18789
```

## Development

```bash
# Install test plugin
helm plugin install https://github.com/helm-unittest/helm-unittest.git

# Run tests (90 tests, 12 suites)
make test

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
```

## License

[MIT](LICENSE)
