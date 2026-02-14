# KubeClaw

A Helm chart for deploying Clawdbot AI agent devpods on Kubernetes.

Reduces deploying a new agent from ~8 files across 3 directories to **2 files**: a HelmRelease values file + a SOPS-encrypted secret.

## Quick Start

```bash
helm install promptver . -f examples/standard.yaml
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

## Values Reference

### Required

| Value | Description |
|-------|-------------|
| `agentName` | Agent identifier. Used for naming, namespace (`devpod-{name}`), and defaults |

### Agent Configuration

| Value | Default | Description |
|-------|---------|-------------|
| `agentDisplayName` | `"{agentName} Dev"` | Human-readable name in Matrix/config |
| `agent.id` | `agentName` | Agent ID in clawdbot.json |
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
| `channels.matrix.homeserver` | `https://matrix.zacx.dev` | Matrix server |
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
| `rawConfig` | `{}` | Full clawdbot.json override (bypasses templating) |
| `image.repository` | `harbor.homelab.lan/library/clawdbot` | Container image |
| `image.tag` | `latest` | Image tag |

## Service Discovery

Each agent is reachable at:
```
{agentName}-devpod.devpod-{agentName}.svc.cluster.local:18789
```

## Architecture

The chart creates:
- **Namespace** `devpod-{agentName}` (optional)
- **Deployment** with startup script that clones repos, sets up SSH/credentials, injects secrets via `jq`, runs `clawdbot gateway`
- **Service** (ClusterIP on port 18789)
- **PVC** for persistent data (`/data`)
- **ConfigMap** with `clawdbot.json` and `repos.json`
- **ConfigMap** for skill `.md` files (if any)
- **ServiceAccount** + **Role/RoleBinding** (namespace reader)
- **ClusterRoleBinding** to cluster-admin (if `rbac.clusterAdmin.enabled`)

Secret tokens (`MATRIX_ACCESS_TOKEN`, etc.) are injected at runtime via environment variables from the referenced Secret, then merged into `clawdbot.json` by `jq` in the startup script.
