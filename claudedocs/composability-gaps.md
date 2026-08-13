# Closing the composability gap

**Status:** planning · **Written:** 2026-08-13 · **Chart at time of writing:** 0.7.1

As of #5 the README positions KubeClaw as a *"lightweight, composable Kubernetes
control plane."* An adversarial audit of the code found that claim holds at the
Kubernetes-resource layer and does **not** hold at the config layer. This doc
records the gap precisely and ranks the work to close it.

The positioning is not wrong for its audience — platform engineers evaluate the
resource layer, and there the composition is real (independent opt-in blocks,
per-agent RBAC tier / egress / storage, verified by `examples/fleet/`). But the
claim would not survive someone arguing composability at the config layer, and
that is a gap worth closing on the merits rather than scoping around forever.

## What "composable" currently means here

**True today.** These are genuinely independent, opt-in, and combine freely:

- `extraConfigMaps`, `extraVolumes`, `extraVolumeMounts`, `extraEnv`,
  `extraInitCommands` — generic Kubernetes extension points, decoupled from
  OpenClaw internals.
- `skills` / `workspaceFiles` / `workspaceContent` — independent maps.
  `pruneStaleSkills` even tracks a manifest so removal never touches
  unmanaged skills.
- RBAC tiers, `networkPolicy`, `snapshots`, `logShipping` — self-contained
  optional resources.

**Not true today.** These are configuration, not composition:

| Gap | Evidence |
|-----|----------|
| `rawConfig` is an all-or-nothing bypass | `templates/configmap.yaml:10-12` — when set, every other config value is silently discarded |
| Config is hand-serialized JSON text | `templates/configmap.yaml` — ~68 lines of manual comma-chaining; a conditional block in the wrong place emits invalid JSON |
| Startup is one sequential block | `templates/deployment.yaml:60-1062` — ordering is load-bearing (skills must run *after* snapshot restore or `rclone sync` deletes them) |
| Workflows are bound to this chart's pod | `templates/cronjob-workflow.yaml:92,154-159` — discovers the Deployment by label, `kubectl exec`s the `openclaw agent` CLI |
| ConfigMap changes restart the whole pod | `templates/deployment.yaml:20-32` — five `checksum/*` annotations, one shared Deployment |

## Ranked work

Ordered by leverage per unit of risk, not by audit order.

| # | Item | Effort | Risk | Leverage | Issue |
|---|------|--------|------|----------|-------|
| 1 | Additive config overlay + dict-based generation | Medium | Low (verifiable) | **High** | [#7](https://github.com/ZacxDev/kubeclaw/issues/7) |
| 2 | Workflow executor indirection | Medium-high | Medium | Medium | [#8](https://github.com/ZacxDev/kubeclaw/issues/8) |
| 3 | Staged startup script — *test first* | High | **High** | Medium | [#9](https://github.com/ZacxDev/kubeclaw/issues/9) |
| 4 | Provider-agnostic config layer | Very high | High | Low until a 2nd agent is real | not filed — YAGNI |
| 5 | Independent ConfigMap lifecycles | Low | Low | **Near zero — see below** | not filed — WONTFIX |

### Item 5 is probably a WONTFIX

The audit listed it, but it does not survive scrutiny. Skills, workspace files
and the email plugin are **copied into the container at startup** by the init
script. A ConfigMap change with no pod restart would leave the running agent
serving the old copy — the restart is not incidental coupling, it is what makes
the change take effect. Making these hot-reloadable means adding a reconcile
loop inside the pod, which is more moving parts in service of a property nobody
has asked for. Recommend closing as "working as intended" unless a concrete
need appears.

### Item 4 is YAGNI for now

A provider-agnostic config layer only pays off if a second agent runtime is
actually going to be supported. The coupling is real and large — 91 `openclaw`
references in `deployment.yaml`, a hand-mirrored `openclaw.json` schema, three
CLI verbs, and 7+ workarounds pinned to specific OpenClaw dot-releases. Until
there is a second target, this is speculative generality. The honest move is
the one already taken in #5: state in the README that OpenClaw is the runtime.

## Item 1 — spec

The highest-leverage change, and the one that most directly contradicts the word
"composable" today.

### Current behavior

```
rawConfig set   → the entire templated config is discarded
rawConfig unset → the templated config is used
```

There is no way to keep the chart's generation and adjust one key. A consumer
who needs a single OpenClaw setting the chart doesn't model must re-author the
whole `openclaw.json` and give up every value the chart resolves for them —
workspace defaulting, mention patterns, channel stripping, secret injection
targets.

### Target behavior

Build the config as a **Helm dict**, then apply an overlay:

```
config = mergeOverwrite (templatedConfigDict) (.Values.configOverlay)
```

This makes `configOverlay` additive and composable: set one key, keep everything
else. It also removes the manual comma-chaining as a side effect, since the dict
is serialized once with `toJson` instead of hand-assembled.

### The backward-compatibility trap

**Do not repurpose `rawConfig` for this.** It is tempting and it is wrong:
someone using `rawConfig` today gets full replacement, and silently converting
that to a merge would inject chart-generated keys into a config they
deliberately authored from scratch. That is exactly the class of silent
fleet-wide default change this repo has been careful to avoid (cf. the 0.7.0
render-diff discipline).

Instead:

- **`rawConfig` keeps replace semantics**, unchanged. Document it as the escape
  hatch of last resort.
- **`configOverlay` is new** and additive. Default `{}` → renders identically
  to today.
- If both are set, `rawConfig` wins and the render **fails loudly** rather than
  silently picking one — same fail-loud posture as the NetworkPolicy guards
  in 0.7.1.

This makes item 1 a purely additive change. No existing agent's rendered config
moves by a byte.

### Verification strategy

A refactor from hand-serialized text to dict-built JSON is exactly the kind of
change that type-checks, passes unit tests, and still ships a subtly different
config. Unit assertions on rendered text are **not** sufficient here.

Required gate, in order:

1. **Semantic render diff.** For every file in `examples/`, `examples/fleet/`,
   `ci/test-values.yaml` and `ci/full-values.yaml`: render before and after,
   extract `data["openclaw.json"]`, parse both as JSON, assert deep equality.
   Byte equality is too strict (key order may move); deep equality is the
   real contract. This is the primary gate — if it is green across all ten
   value files, the refactor is behavior-preserving.
2. **Negative control on the harness itself.** Before trusting the diff tool,
   feed it two configs that differ by one nested key and confirm it reports a
   difference. A comparison harness that always reports "identical" is the
   default failure mode here.
3. **Overlay behavior tests.** New unit tests: overlay sets a new key; overlay
   overrides an existing nested key without dropping its siblings; overlay
   empty renders identically to no overlay; `rawConfig` + `configOverlay`
   together fails the render.
4. **Strengthen the existing `rawConfig` test.** It currently only asserts the
   rendered text matches `"custom"` (`tests/configmap_test.yaml:55-64`) — it
   does not verify that the templated config was actually bypassed. Add an
   assertion that a chart-generated key is *absent*.
5. `make test-shell` unchanged and green — the startup script's semantic
   config-revert detection reads specific scalars out of the generated config,
   so a key that moves would surface there.

### Sequencing

Item 1 lands first and alone. It is additive, independently verifiable, and it
makes items 2-3 easier by giving the chart a real config object instead of a
string. Do not bundle it with the startup-script work.

## Item 2 — sketch

Workflow CronJobs hardcode `openclaw agent --agent <id> --message <msg>` and pod
discovery by label. Introduce an indirection — a values-level `executor` block
naming the command template and the discovery selector — so a workflow can
target something other than this chart's own pod. Lower priority than item 1
and lower leverage; the coupling is honest today and nobody is currently blocked
by it.

## Item 3 — warning

Splitting the 1,002-line startup script into stages is the riskiest change in
this list. The ordering is load-bearing in at least one non-obvious place
(snapshot restore before skills, or rclone deletes them) and the script has no
integration test that would catch a re-ordering regression — `make test-shell`
covers two behaviors, not the sequence. **Do not attempt this without first
building a test that pins the ordering contract.** That test is arguably the
real deliverable of item 3, and could be built independently of any refactor.
