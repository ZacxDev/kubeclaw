---
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
argument-hint: <deploy|workflow|debug|template> [args]
description: Deploy and manage Clawdbot agent devpods with KubeClaw
---

# KubeClaw Usage Skill

You are helping a user deploy and manage Clawdbot AI agent devpods using the KubeClaw Helm chart.

## Chart Location

The KubeClaw chart is at the current working directory. The homelab-talos repo (where HelmReleases live) is at `~/workspace/homelab-talos/`.

## Actions

Parse `$ARGUMENTS` to determine the action:

- **deploy** — Generate a complete HelmRelease + namespace + secret for a new agent
- **workflow** — Add or modify workflows in an agent's values
- **debug** — Troubleshoot a rendered chart or running agent
- **template** — Quick `helm template` with specific values or overrides

If no action is given or it's unclear, ask the user what they want to do.

---

## Action: deploy

Generate a complete set of files for deploying a new agent via FluxCD.

### Interactive Wizard

Ask the user for:
1. **Agent name** (lowercase, alphanumeric + hyphens) — used for naming everything
2. **Variant** — `standard`, `coordinator`, or `infrastructure` (show descriptions below)
3. **Git repos** — list of repos to clone (url, path, branch)
4. **Skills** — any skill files to embed (or skip for now)
5. **Target cluster** — `homelab`, `workbench`, or `production`

### Variant Descriptions
- **standard**: Basic agent with git repos, skills, and Matrix/Telegram channels
- **coordinator**: Meta-agent that coordinates other agents. Gets an agents-registry ConfigMap
- **infrastructure**: Cluster admin agent with kubectl, flux, sops, age installed. Gets kubeconfig access

### Output Files

Generate files in `~/workspace/homelab-talos/clusters/{cluster}/apps/{agent-name}/`:

```
{agent-name}/
├── namespace.yaml          # Only if not using chart's namespace creation
├── helmrelease.yaml        # FluxCD HelmRelease pointing to KubeClaw chart
├── secret.enc.yaml         # SOPS-encrypted secret (placeholder keys)
└── kustomization.yaml      # FluxCD Kustomization resource
```

### HelmRelease Template

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: {agent-name}
  namespace: devpod-{agent-name}
spec:
  interval: 5m
  chart:
    spec:
      chart: .
      sourceRef:
        kind: GitRepository
        name: kubeclaw
        namespace: flux-system
      reconcileStrategy: Revision
  values:
    agentName: {agent-name}
    # ... values based on variant and user input
```

### Kustomization Template

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: devpod-{agent-name}
resources:
  - helmrelease.yaml
  - secret.enc.yaml
```

### Secret Template

Create a SOPS-encrypted secret with placeholder keys. The expected secret keys are:
- `MATRIX_ACCESS_TOKEN` — Matrix bot token
- `TELEGRAM_BOT_TOKEN` — Telegram bot token (optional)
- `HOOKS_TOKEN` — Webhook authentication token
- `GITHUB_TOKEN` — GitHub personal access token
- `BRAVE_API_KEY` — Brave Search API key
- `ANTHROPIC_API_KEY` — Claude API key
- `git-ssh-key` — SSH private key for git operations
- `claude-credentials.json` — Claude OAuth credentials JSON

Ask which keys the user needs and generate accordingly.

After generating, remind the user to:
1. Add the app directory to the cluster's `apps/kustomization.yaml`
2. Encrypt the secret: `sops --encrypt --in-place secret.enc.yaml`
3. Commit and push to trigger FluxCD deployment

---

## Action: workflow

Add or modify workflows in an agent's values.

### Workflow Schema Reference

```yaml
workflows:
  <workflow-name>:
    schedule: "0 10 * * *"          # REQUIRED: Cron expression
    timeout: 1800                   # Job deadline (seconds), default: 900
    agent: ""                       # Agent ID override (defaults to agentName)
    gitSync: true                   # Pull repos before running
    concurrencyPolicy: Forbid       # Forbid|Replace|Allow
    suspend: false                  # Pause scheduling
    context:                        # Custom env vars available in steps
      CUSTOM_VAR: "value"
    report:
      path: "path/{{workflow}}-{{date}}.md"
      commit: true                  # Auto git commit+push
      branch: "trunk"
      repo: ""                      # Repo path (defaults to first git.repos entry)
    notify:
      telegram:
        chatId: ""                  # Telegram chat ID for notifications
    steps:
      - name: "step-name"          # REQUIRED: unique step identifier
        skill: |                   # Inline skill content (OR use skillRef)
          Instructions for the agent...
        skillRef: ""               # Path to skill file on agent pod
        timeout: 300               # Per-step timeout (seconds)
        notify: false              # Send step output to Telegram
```

### Context Variables Available in Steps

These are automatically available as environment variables in workflow CronJobs:
- `$OUTPUT_DIR` — Shared temp directory for inter-step communication
- `$REPORT_PATH` — Report file path (rendered from `report.path`)
- `$DATE` — Current date (YYYYMMDD)
- `$WORKFLOW` — Workflow name
- `$STEP` — Current step name
- Any custom keys from the `context:` map

### Template Variables in report.path

- `{{workflow}}` — Workflow name
- `{{date}}` — Current date (YYYYMMDD)

### Workflow Guidelines

- Use `skill:` for inline instructions, `skillRef:` for existing skill files on the agent
- Steps execute sequentially — each step's output is available to the next via `$OUTPUT_DIR`
- Set `notify: true` on a step to send its output to Telegram
- Reports are auto-committed with `Co-Authored-By: Clawdbot` footer
- Use `suspend: true` to temporarily disable a workflow without deleting it

### Preview

After modifying workflow values, preview the rendered CronJob:
```bash
helm template {agent-name} . -f {values-file} -s templates/cronjob-workflow.yaml
```

---

## Action: debug

Troubleshoot a rendered chart or running agent.

### Steps

1. Ask the user for the values file or agent name
2. Render templates: `helm template {name} . -f {values-file}`
3. Check for common issues:
   - **Missing agentName**: The chart requires `agentName` to be set
   - **Bad cron schedule**: Validate schedule syntax in workflows
   - **Missing secret reference**: Check `existingSecret` matches actual secret name
   - **Resource conflicts**: Check for duplicate names or namespace collisions
   - **Workflow issues**: Verify steps have either `skill` or `skillRef`, not both or neither

### Running Agent Diagnostics

If debugging a live agent:
```bash
# Check pod status
KUBECONFIG=~/workspace/homelab-talos/{cluster}-kubeconfig kubectl get pods -n devpod-{agent}

# Check pod logs
KUBECONFIG=~/workspace/homelab-talos/{cluster}-kubeconfig kubectl logs -n devpod-{agent} deploy/{agent}-devpod -f

# Check HelmRelease status
KUBECONFIG=~/workspace/homelab-talos/{cluster}-kubeconfig flux get helmrelease -n devpod-{agent} {agent}

# Check workflow CronJobs
KUBECONFIG=~/workspace/homelab-talos/{cluster}-kubeconfig kubectl get cronjobs -n devpod-{agent}

# Check recent workflow job logs
KUBECONFIG=~/workspace/homelab-talos/{cluster}-kubeconfig kubectl get jobs -n devpod-{agent} --sort-by=.metadata.creationTimestamp
```

### Service Discovery

Agent pods expose a clawdbot gateway on port 18789:
- Internal: `{agent}-devpod.devpod-{agent}.svc:18789`
- Workflow CronJobs use `kubectl exec` into the running pod, not the service

---

## Action: template

Quick `helm template` rendering.

### Usage

```bash
# With a values file
helm template {name} . -f {values-file}

# With inline overrides
helm template {name} . --set agentName={name} --set rbac.clusterAdmin.enabled=true

# Specific template only
helm template {name} . -f {values-file} -s templates/deployment.yaml

# With a values file from examples/
helm template myagent . -f examples/standard.yaml
```

### Available Examples

| File | Description |
|------|-------------|
| `examples/standard.yaml` | Basic agent with git repo and skill |
| `examples/coordinator.yaml` | Meta-coordinator with agents registry |
| `examples/infrastructure.yaml` | Cluster admin with infra tools |
| `examples/workflow-product-iteration.yaml` | 3-step product intelligence pipeline |
| `examples/workflow-stock-news.yaml` | Single-step daily stock summary |

---

## Values Quick Reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `agentName` | string | **required** | Agent identifier |
| `agentDisplayName` | string | `"{agentName} Dev"` | Human-readable name |
| `agent.id` | string | `agentName` | Agent ID in config |
| `agent.workspace` | string | first repo path | Working directory |
| `agent.maxConcurrent` | int | `4` | Max concurrent sessions |
| `agent.model.primary` | string | `anthropic/claude-sonnet-4` | AI model |
| `image.repository` | string | `harbor.homelab.lan/library/clawdbot` | Container image |
| `image.tag` | string | `latest` | Image tag |
| `git.repos` | list | `[]` | Git repos to clone `[{url, path, branch}]` |
| `skills` | map | `{}` | Skill files `{filename.md: content}` |
| `existingSecret` | string | `""` | Pre-existing Secret name |
| `namespace.create` | bool | `true` | Create namespace |
| `rbac.create` | bool | `true` | Create RBAC resources |
| `rbac.clusterAdmin.enabled` | bool | `false` | Cluster-admin binding |
| `infraTools.enabled` | bool | `false` | Install kubectl, flux, etc. |
| `persistence.enabled` | bool | `true` | Enable PVC |
| `persistence.size` | string | `10Gi` | PVC size |
| `workflows` | map | `{}` | Workflow definitions |
| `resources.requests.memory` | string | `512Mi` | Memory request |
| `resources.limits.memory` | string | `2Gi` | Memory limit |
