# Fleet example — three agents, three trust tiers

The same chart, composed three different ways. Each file is a complete
per-agent values file; deploy them as three HelmReleases pointing at one
GitRepository source.

| Agent | RBAC tier | Egress | Hardening | Features on |
|-------|-----------|--------|-----------|-------------|
| `reviewer.yaml` | namespace reader (default) | GitHub + Anthropic only | caps dropped, TLS verify on | skills |
| `ops-readonly.yaml` | cluster `view` | + tool CDNs, apiserver | baseline (caps kept) | infraTools |
| `orchestrator.yaml` | orchestrator ClusterRole | + S3, apiserver | baseline (caps kept) | workflows, snapshots, logShipping |

The point: **trust tier, blast radius and feature set are independent axes.**
`reviewer` is the most locked-down agent but has the fewest moving parts;
`orchestrator` is the most privileged but still cannot reach the internet
outside its allowlist.

## Render them

```bash
helm template reviewer     .. -f reviewer.yaml
helm template ops-readonly .. -f ops-readonly.yaml
helm template orchestrator .. -f orchestrator.yaml
```

Or from the chart root: `make template-fleet`.

## Two things to copy carefully

**Egress is exact-host.** `matchName` does not do subdomains. `github.com`
covers neither `api.github.com` (the `gh` CLI) nor `codeload.github.com`
(git archive and some clones). Every host an agent touches must be listed,
including the ones its *tools* touch — see `ops-readonly.yaml`, where
enabling `infraTools` means the pod curls `dl.k8s.io`, `fluxcd.io` and
GitHub release assets at startup.

**Dropping capabilities is not free.** `reviewer` sets
`capabilities.drop: ["ALL"]` because its dependencies are baked into the
image. The other two do **not**, because `infraTools` and the snapshot
`rclone` install write binaries and unpack a `.deb` at container init,
which needs CHOWN/DAC_OVERRIDE/FOWNER. Dropping caps there fails the pod
at startup, not at render time.
