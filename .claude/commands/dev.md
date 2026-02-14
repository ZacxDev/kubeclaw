---
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
argument-hint: <test|lint|template|add-template|add-test|release> [args]
description: Develop, test, and release the KubeClaw Helm chart
---

# KubeClaw Development Skill

You are helping a developer modify the KubeClaw Helm chart — its templates, tests, values, and release process.

## Repository Structure

```
kubeclaw/
├── Chart.yaml                 # Chart metadata (name, version, appVersion)
├── values.yaml                # Default values with full schema
├── Makefile                   # Build/test automation
├── templates/                 # 17 Helm templates
│   ├── _helpers.tpl           # Helper functions
│   ├── deployment.yaml        # Agent pod (283 lines, most complex)
│   ├── cronjob-workflow.yaml  # Workflow CronJobs (243 lines)
│   ├── configmap.yaml         # openclaw.json config
│   ├── configmap-skills.yaml  # Skill files ConfigMap
│   ├── configmap-workflow-skills.yaml
│   ├── configmap-extra.yaml   # Extra ConfigMaps
│   ├── namespace.yaml         # Namespace
│   ├── service.yaml           # ClusterIP service
│   ├── pvc.yaml               # PersistentVolumeClaim
│   ├── serviceaccount.yaml    # Agent SA
│   ├── role.yaml              # Agent Role
│   ├── rolebinding.yaml       # Agent RoleBinding
│   ├── clusterrolebinding.yaml
│   ├── serviceaccount-workflow.yaml
│   ├── role-workflow.yaml
│   ├── rolebinding-workflow.yaml
│   └── NOTES.txt              # Install notes
├── tests/                     # 12 test files, 90+ tests
├── examples/                  # 5 example values files
├── ci/                        # CI test values
└── docs/                      # Additional documentation
```

## Actions

Parse `$ARGUMENTS` to determine the action:

- **test** — Run helm-unittest, analyze results
- **lint** — Run helm lint
- **template** — Render templates for debugging
- **add-template** — Guide for adding a new template
- **add-test** — Guide for adding tests
- **release** — Version bump and release workflow

If no action is given or it's unclear, ask the user what they want to do.

---

## Action: test

Run the helm-unittest test suite.

```bash
# Run all tests
helm unittest .

# Run a specific test file
helm unittest . -f 'tests/deployment_test.yaml'

# Run with verbose output
helm unittest . -v

# Using Makefile
make test
```

### Test File Mapping

| Test File | Template(s) Covered |
|-----------|-------------------|
| `tests/deployment_test.yaml` | deployment.yaml (+ configmap.yaml, configmap-skills.yaml for checksums) |
| `tests/configmap_test.yaml` | configmap.yaml |
| `tests/configmap-skills_test.yaml` | configmap-skills.yaml |
| `tests/configmap-extra_test.yaml` | configmap-extra.yaml |
| `tests/namespace_test.yaml` | namespace.yaml |
| `tests/service_test.yaml` | service.yaml |
| `tests/pvc_test.yaml` | pvc.yaml |
| `tests/rbac_test.yaml` | serviceaccount.yaml, role.yaml, rolebinding.yaml, clusterrolebinding.yaml |
| `tests/notes_test.yaml` | NOTES.txt |
| `tests/workflow-cronjob_test.yaml` | cronjob-workflow.yaml |
| `tests/workflow-configmap_test.yaml` | configmap-workflow-skills.yaml |
| `tests/workflow-rbac_test.yaml` | serviceaccount-workflow.yaml, role-workflow.yaml, rolebinding-workflow.yaml |

### Analyzing Failures

When tests fail:
1. Read the failing test file to understand the expected assertion
2. Read the corresponding template to understand actual rendering
3. Use `helm template test . --set agentName=test -s templates/{file}` to see rendered output
4. Compare rendered output against test expectations

---

## Action: lint

Run Helm linting to catch syntax and schema errors.

```bash
# Basic lint (agentName is required)
helm lint . --set agentName=test

# With a values file
helm lint . -f examples/standard.yaml

# Using Makefile
make lint
```

---

## Action: template

Render templates for inspection and debugging.

```bash
# Full render with example values
helm template myagent . -f examples/standard.yaml

# Specific template only
helm template myagent . --set agentName=myagent -s templates/deployment.yaml

# With overrides
helm template myagent . -f examples/standard.yaml --set persistence.size=50Gi

# Using Makefile (renders standard example)
make template

# Render all main examples
make template-all
```

---

## Action: add-template

Guide for adding a new Kubernetes resource template to the chart.

### Naming Convention

- File: `templates/{resource-type}.yaml` (e.g., `templates/ingress.yaml`)
- Resource name: `{{ include "kubeclaw.fullname" . }}-{suffix}` or just `{{ include "kubeclaw.fullname" . }}`
- Namespace: `{{ include "kubeclaw.namespace" . }}`

### Template Skeleton

```yaml
{{- if .Values.featureFlag.enabled }}
apiVersion: {api-version}
kind: {Kind}
metadata:
  name: {{ include "kubeclaw.fullname" . }}-{suffix}
  namespace: {{ include "kubeclaw.namespace" . }}
  labels:
    {{- include "kubeclaw.labels" . | nindent 4 }}
spec:
  # ... resource spec
{{- end }}
```

### Checklist

1. Wrap in conditional if the resource is optional (`{{- if ... }}`)
2. Include standard labels via `{{ include "kubeclaw.labels" . | nindent 4 }}`
3. Use `{{ include "kubeclaw.namespace" . }}` for the namespace
4. Add any new values to `values.yaml` with sensible defaults
5. Create corresponding test file in `tests/`
6. Update `examples/` if the feature is user-facing
7. Run `make lint && make test` to validate

### Helper Functions Reference

| Helper | Output | Usage |
|--------|--------|-------|
| `kubeclaw.fullname` | `{agentName}` (truncated 63 chars) | Resource names |
| `kubeclaw.namespace` | `devpod-{agentName}` | All resource namespaces |
| `kubeclaw.displayName` | `{agentDisplayName}` or `{agentName} Dev` | Human-readable |
| `kubeclaw.agentId` | `agent.id` or `agentName` | Config agent ID |
| `kubeclaw.workspace` | First repo path or `/data/workspace` | Working directory |
| `kubeclaw.mentionPatterns` | `["@{name}", "{name}"]` | Matrix triggers |
| `kubeclaw.secretName` | `existingSecret` or `{fullname}-secrets` | Secret reference |
| `kubeclaw.chart` | `kubeclaw-0.2.0` | Chart identifier |
| `kubeclaw.labels` | Standard labels block | All resources |
| `kubeclaw.selectorLabels` | `app.kubernetes.io/name=devpod`, etc. | Selectors |
| `kubeclaw.pvcName` | `existingClaim` or `{fullname}-data` | PVC reference |
| `kubeclaw.hasWorkflows` | `true`/`false` | Workflow conditional |
| `kubeclaw.workflowSaName` | `{agentName}-workflow` | Workflow SA name |
| `kubeclaw.workflowLabels` | Labels with `component=workflow` | Workflow resources |
| `kubeclaw.workflowAgentId` | Workflow agent override or default | Workflow config |

---

## Action: add-test

Guide for writing helm-unittest tests.

### File Naming

- Test file: `tests/{template-name}_test.yaml` (e.g., `tests/ingress_test.yaml`)
- Test files map to template files — name them to match

### Test Structure

```yaml
suite: {Template Name}
templates:
  - templates/{template-file}.yaml
tests:
  - it: should {describe expected behavior}
    set:
      agentName: test-agent
      # ... values to set
    asserts:
      - isKind:
          of: {Kind}
      - equal:
          path: metadata.name
          value: expected-name
```

### Common Assertions

| Assertion | Description | Example |
|-----------|-------------|---------|
| `isKind` | Check resource kind | `isKind: { of: Deployment }` |
| `equal` | Exact value match | `equal: { path: metadata.name, value: foo }` |
| `contains` | Array contains item | `contains: { path: spec.volumes, content: { name: data } }` |
| `hasDocuments` | Number of rendered docs | `hasDocuments: { count: 2 }` |
| `matchRegex` | Regex match on value | `matchRegex: { path: metadata.name, pattern: "^test-" }` |
| `isNotEmpty` | Value exists and non-empty | `isNotEmpty: { path: spec.template }` |
| `isNull` | Value is null/missing | `isNull: { path: spec.nodeSelector }` |
| `isSubset` | Object is subset | `isSubset: { path: metadata.labels, content: { app: foo } }` |
| `failedTemplate` | Template should fail | `failedTemplate: { errorMessage: "required" }` |
| `notEqual` | Value does not match | `notEqual: { path: spec.replicas, value: 0 }` |

### Multi-Template Tests

When a template references another (e.g., deployment checksums configmaps), include all relevant templates:

```yaml
suite: Deployment
templates:
  - templates/deployment.yaml
  - templates/configmap.yaml          # Needed for checksum annotation
  - templates/configmap-skills.yaml   # Needed for checksum annotation
tests:
  - it: should render deployment
    set:
      agentName: test
    asserts:
      - isKind:
          of: Deployment
```

### Testing Conditionals

```yaml
  - it: should not render when disabled
    set:
      agentName: test
      featureFlag:
        enabled: false
    asserts:
      - hasDocuments:
          count: 0
```

### Testing Multiple Documents

When a template renders multiple documents (e.g., one per workflow), use `documentIndex`:

```yaml
  - it: should render second workflow
    set:
      agentName: test
      workflows:
        first:
          schedule: "0 * * * *"
          steps:
            - name: step1
              skill: "do thing"
        second:
          schedule: "0 12 * * *"
          steps:
            - name: step1
              skill: "do other thing"
    documentIndex: 1
    asserts:
      - equal:
          path: metadata.name
          value: test-second
```

### Checklist for New Tests

1. Create test file matching template name
2. Set `suite:` to describe the template
3. List template(s) under `templates:`
4. Always set `agentName` in test values (it's required)
5. Test the happy path (default values render correctly)
6. Test conditionals (feature enabled/disabled)
7. Test edge cases (empty values, overrides)
8. Run `helm unittest .` to validate all pass

---

## Action: release

Version bump and release workflow.

### Steps

1. **Run tests**: `make lint && make test`
2. **Bump version** in `Chart.yaml`:
   - Patch: bug fixes, doc updates (0.2.0 → 0.2.1)
   - Minor: new features, new templates (0.2.0 → 0.3.0)
   - Major: breaking changes (0.2.0 → 1.0.0)
3. **Update appVersion** if the openclaw image tag changed
4. **Commit**: `git commit -m "chore: bump kubeclaw to v{version}"`
5. **Push**: `git push origin trunk`

### Pre-Release Checklist

- [ ] All tests pass (`make test`)
- [ ] Linting passes (`make lint`)
- [ ] All examples render cleanly (`make template-all`)
- [ ] New features have tests
- [ ] New features have example values
- [ ] values.yaml comments are up to date
- [ ] Chart.yaml version bumped

---

## Makefile Targets

| Target | Command | Description |
|--------|---------|-------------|
| `make lint` | `helm lint . --set agentName=test` | Validate chart syntax |
| `make test` | `helm unittest .` | Run all unit tests |
| `make template` | `helm template standard . -f examples/standard.yaml` | Render standard example |
| `make template-all` | Renders standard + coordinator + infrastructure | Render main examples |
| `make clean` | `rm -rf charts/ Chart.lock` | Clean build artifacts |

## Naming Conventions

| Resource | Pattern | Example |
|----------|---------|---------|
| Deployment | `{agentName}-devpod` | `jarvis-devpod` |
| Service | `{agentName}-devpod` | `jarvis-devpod` |
| Namespace | `devpod-{agentName}` | `devpod-jarvis` |
| ServiceAccount | `{agentName}-devpod` | `jarvis-devpod` |
| Workflow SA | `{agentName}-workflow` | `jarvis-workflow` |
| PVC | `{agentName}-data` | `jarvis-data` |
| ConfigMap | `{agentName}-config` | `jarvis-config` |
| Skills CM | `{agentName}-skills` | `jarvis-skills` |
| Workflow CronJob | `{agentName}-{workflowName}` | `jarvis-daily-report` |
| Workflow Skills CM | `{agentName}-wf-{workflowName}-skills` | `jarvis-wf-daily-report-skills` |
