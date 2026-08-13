CHART_DIR := .
RELEASE_NAME := test

# Recipes use bash features (`set -o pipefail`), but make defaults to /bin/sh.
# That is bash on NixOS and dash on Ubuntu, so a recipe can pass on a dev box
# and fail in CI with "Illegal option -o pipefail" — which is exactly how this
# was found (first CI run on PR #14).
#
# Resolved via `command -v` rather than hardcoded: /bin/bash does not exist on
# NixOS, so `SHELL := /bin/bash` would fix CI and break local development.
SHELL := $(shell command -v bash)

.PHONY: lint test test-shell render-diff byte-diff template template-all template-fleet clean

lint:
	helm lint $(CHART_DIR) --set agentName=test

test:
	helm unittest $(CHART_DIR)

# Runtime behavior tests for the safety-critical startup-script logic
# (skill prune / config-revert detection) that helm-unittest can't execute.
# Extracts the rendered inline script and runs it under sh against fixtures.
# Requires: helm, jq, and python3 with PyYAML on PATH. On NixOS:
#   nix-shell -p kubernetes-helm jq "python3.withPackages(p: [p.pyyaml])" --run "make test-shell"
test-shell:
	bash $(CHART_DIR)/tests/shell/run.sh

template:
	helm template $(RELEASE_NAME) $(CHART_DIR) -f examples/standard.yaml

template-all:
	@echo "=== standard ==="
	helm template $(RELEASE_NAME) $(CHART_DIR) -f examples/standard.yaml
	@echo ""
	@echo "=== coordinator ==="
	helm template $(RELEASE_NAME) $(CHART_DIR) -f examples/coordinator.yaml
	@echo ""
	@echo "=== infrastructure ==="
	helm template $(RELEASE_NAME) $(CHART_DIR) -f examples/infrastructure.yaml

# Semantic render diff of the generated openclaw.json against a git ref
# (default: trunk). Use before/after ANY change to config generation — unit
# assertions on rendered text cannot catch a config whose meaning moved.
# Runs the harness's own negative control first; `compare` refuses to run
# until that has demonstrated it can detect a difference.
#   make render-diff            # vs trunk
#   make render-diff REF=v0.7.1 # vs a tag
REF ?= trunk
render-diff:
	@set -e; \
	 python3 $(CHART_DIR)/scripts/render-diff.py selftest; \
	 tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	 mkdir -p $$tmp/ref && git -C $(CHART_DIR) archive $(REF) | tar -x -C $$tmp/ref; \
	 mkdir -p $$tmp/ref/scripts; cp $(CHART_DIR)/scripts/render-diff.py $$tmp/ref/scripts/; \
	 echo "--- capturing $(REF) ---"; python3 $$tmp/ref/scripts/render-diff.py capture $$tmp/a; \
	 echo "--- capturing working tree ---"; python3 $(CHART_DIR)/scripts/render-diff.py capture $$tmp/b; \
	 echo "--- comparing ---"; python3 $(CHART_DIR)/scripts/render-diff.py compare $$tmp/a $$tmp/b

# Full-manifest BYTE diff vs a git ref, with the chart version normalised on
# both sides so a routine version bump doesn't mask real byte drift.
#
# render-diff compares the MEANING of openclaw.json. This compares the bytes of
# every rendered manifest, which is what checksum/config hashes — and that
# annotation rolling-restarts the whole fleet when it moves. The two catch
# different things: dropping the trailing dash on configmap.yaml's `{{- end -}}`
# leaves render-diff at 10/10 identical while moving the checksum. Run BOTH
# before shipping a change to config generation.
byte-diff:
	@set -e -o pipefail; \
	 tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	 mkdir -p $$tmp/ref $$tmp/wt; \
	 git -C $(CHART_DIR) archive $(REF) | tar -x -C $$tmp/ref; \
	 tar -c --exclude=./.git --exclude=./.venv --exclude=./.direnv -C $(CHART_DIR) . | tar -x -C $$tmp/wt; \
	 sed -i 's/^version:.*/version: 0.0.0-bytediff/' $$tmp/ref/Chart.yaml $$tmp/wt/Chart.yaml; \
	 rc=0; n=0; \
	 for f in examples/*.yaml examples/fleet/*.yaml ci/*.yaml; do \
	   [ -f "$$tmp/wt/$$f" ] || continue; \
	   out_a=$$(helm template bd $$tmp/ref -f $$tmp/ref/$$f) || \
	     { echo "FATAL: helm failed rendering $(REF):$$f"; exit 2; }; \
	   out_b=$$(helm template bd $$tmp/wt  -f $$tmp/wt/$$f) || \
	     { echo "FATAL: helm failed rendering working-tree:$$f"; exit 2; }; \
	   [ -n "$$out_a" ] || { echo "FATAL: $(REF):$$f rendered EMPTY"; exit 2; }; \
	   a=$$(printf '%s' "$$out_a" | sha256sum | cut -d' ' -f1); \
	   b=$$(printf '%s' "$$out_b" | sha256sum | cut -d' ' -f1); \
	   n=$$((n+1)); \
	   if [ "$$a" != "$$b" ]; then echo "  BYTE-DIFF $$f"; rc=1; else echo "  same      $$f"; fi; \
	 done; \
	 if [ $$n -eq 0 ]; then echo "FATAL: compared 0 value files"; exit 2; fi; \
	 echo "compared $$n value files (chart version normalised)"; \
	 exit $$rc

# Render the three-agent fleet example. Each agent is a different RBAC tier
# and egress posture from the same chart.
template-fleet:
	@for a in reviewer ops-readonly orchestrator; do \
		echo "=== $$a ==="; \
		helm template $$a $(CHART_DIR) -f $(CHART_DIR)/examples/fleet/$$a.yaml || exit 1; \
	done

clean:
	rm -rf $(CHART_DIR)/charts $(CHART_DIR)/Chart.lock
