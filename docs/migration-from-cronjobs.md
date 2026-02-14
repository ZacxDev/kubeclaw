# Migrating from CronJob YAML to KubeClaw Workflows

This guide maps existing hand-written CronJob YAML to equivalent KubeClaw workflow definitions.

## Overview

| Before (CronJob YAML) | After (KubeClaw Workflow) |
|----------------------|--------------------------|
| ~94-156 lines per CronJob | ~30-40 lines in values |
| Manual pod discovery script | Automatic pod discovery |
| Manual RBAC (SA + Role + RoleBinding) | Shared RBAC across all workflows |
| Manual Telegram notification code | Declarative `notify.telegram.chatId` |
| Manual git commit script | Declarative `report.commit: true` |
| Manual session ID generation | Automatic unique session IDs |

## Migration Steps

### 1. Identify Existing CronJobs

Find all CronJob YAML files in your cluster:

```bash
grep -rl "kind: CronJob" clusters/
```

### 2. Map CronJob Fields

| CronJob YAML | Workflow Values |
|-------------|----------------|
| `spec.schedule` | `workflows.<name>.schedule` |
| `spec.concurrencyPolicy` | `workflows.<name>.concurrencyPolicy` |
| `spec.suspend` | `workflows.<name>.suspend` |
| `spec.jobTemplate.spec.activeDeadlineSeconds` | `workflows.<name>.timeout` |
| `env.CHAT_ID` | `workflows.<name>.notify.telegram.chatId` |
| `env.TELEGRAM_BOT_TOKEN` (secretKeyRef) | Automatic from `existingSecret` |
| Pod exec script body | `workflows.<name>.steps[].skill` |
| ServiceAccount + Role + RoleBinding | Automatic (shared across workflows) |

### 3. Map Script Patterns

#### Pod Discovery
```yaml
# Before: Manual in script
POD=$(kubectl get pods -n clawdbot -l app.kubernetes.io/name=clawdbot ...)

# After: Automatic — KubeClaw uses app.kubernetes.io/instance label
# No action needed
```

#### Git Sync
```yaml
# Before: Manual git pull in script
kubectl exec "$POD" -- git -C /data/repo pull origin trunk

# After: Declarative
workflows:
  my-workflow:
    gitSync: true  # default, pulls all repos
```

#### Agent Invocation
```yaml
# Before: Manual clawdbot agent call
kubectl exec "$POD" -- clawdbot agent \
  --agent promptver-dev \
  --session-id "generate-ideas-$(date +%Y%m%d-%H%M%S)" \
  --message "..." \
  --timeout 900

# After: Declarative step
steps:
  - name: generate-ideas
    timeout: 900
    skill: |
      Your agent instructions here...
```

#### Telegram Notifications
```yaml
# Before: ~20 lines of tmpfile + jq + curl + retry
TMPFILE=$(mktemp)
printf '%s' "$SUMMARY" > "$TMPFILE"
PAYLOAD=$(jq -n --rawfile text "$TMPFILE" ...)
curl -s -X POST "https://api.telegram.org/bot..." ...

# After: Declarative
notify:
  telegram:
    chatId: "YOUR_CHAT_ID"
steps:
  - name: my-step
    notify: true  # sends step output to Telegram
```

#### Report Commit
```yaml
# Before: Manual git add/commit/push
kubectl exec "$POD" -- sh -c "cd /data/repo && \
  git add report.md && \
  git diff --cached --quiet || \
  git commit -m '...' && git push origin trunk"

# After: Declarative
report:
  path: "reports/{{workflow}}-{{date}}.md"
  commit: true
  branch: "trunk"
```

## Example: generate-ideas Migration

### Before (156 lines)

```yaml
# generate-ideas-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: generate-ideas
  namespace: clawdbot
spec:
  schedule: "0 10 */3 * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      activeDeadlineSeconds: 2700
      template:
        spec:
          serviceAccountName: repo-summary
          restartPolicy: Never
          containers:
            - name: generate-ideas
              image: bitnami/kubectl:latest
              env:
                - name: CHAT_ID
                  value: "YOUR_CHAT_ID"
                - name: TELEGRAM_BOT_TOKEN
                  valueFrom:
                    secretKeyRef: ...
              command:
                - /bin/sh
                - -c
                - |
                  # 120+ lines of shell script:
                  # pod discovery, git pull, clawdbot agent calls,
                  # telegram notification with retry,
                  # git commit/push, error handling...
```

Plus: ServiceAccount, Role, RoleBinding YAML (~30 lines).

### After (35 lines in HelmRelease values)

```yaml
workflows:
  product-iteration:
    schedule: "0 10 */3 * *"
    timeout: 2700
    agent: promptver-dev
    context:
      PROMETHEUS_URL: "http://prometheus.example.com:9090"
      LOKI_URL: "http://loki.example.com:3100"
    report:
      path: "claudedocs/reports/product-ideas-{{date}}.md"
      commit: true
      branch: "trunk"
    notify:
      telegram:
        chatId: "YOUR_CHAT_ID"
    steps:
      - name: gather
        timeout: 900
        skill: |
          Gather metrics and feedback...
      - name: synthesize
        timeout: 900
        notify: true
        skill: |
          Synthesize into report...
      - name: implement-plan
        timeout: 900
        skill: |
          Generate implementation plans...
```

RBAC is automatic — shared ServiceAccount, Role, and RoleBinding across all workflows.

## Example: stock-news Migration

### Before (94 lines)
CronJob YAML with pod discovery, agent invocation, Telegram notification script.

### After (12 lines)
```yaml
workflows:
  daily-stocks:
    schedule: "0 13 * * 1-5"
    timeout: 600
    agent: stockbot
    notify:
      telegram:
        chatId: "YOUR_CHAT_ID"
    steps:
      - name: market-summary
        timeout: 300
        notify: true
        skill: |
          Summarize market news...
```

## Cleanup After Migration

Once workflows are working via KubeClaw:

1. Delete the old CronJob YAML files
2. Delete the dedicated ServiceAccount/Role/RoleBinding (now shared)
3. Remove old CronJob resources from kustomization.yaml
4. Commit and push — FluxCD will prune the old resources
