CHART_DIR := .
RELEASE_NAME := test

.PHONY: lint test test-shell render-diff template template-all template-fleet clean

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
	@python3 $(CHART_DIR)/scripts/render-diff.py selftest
	@tmp=$$(mktemp -d); \
	 mkdir -p $$tmp/ref && git -C $(CHART_DIR) archive $(REF) | tar -x -C $$tmp/ref; \
	 cp $(CHART_DIR)/scripts/render-diff.py $$tmp/ref/scripts/ 2>/dev/null || \
	   (mkdir -p $$tmp/ref/scripts && cp $(CHART_DIR)/scripts/render-diff.py $$tmp/ref/scripts/); \
	 touch $$tmp/ref/.selftest-passed; \
	 echo "--- capturing $(REF) ---"; python3 $$tmp/ref/scripts/render-diff.py capture $$tmp/a; \
	 echo "--- capturing working tree ---"; python3 $(CHART_DIR)/scripts/render-diff.py capture $$tmp/b; \
	 echo "--- comparing ---"; python3 $(CHART_DIR)/scripts/render-diff.py compare $$tmp/a $$tmp/b; \
	 rc=$$?; rm -rf $$tmp; exit $$rc

# Render the three-agent fleet example. Each agent is a different RBAC tier
# and egress posture from the same chart.
template-fleet:
	@for a in reviewer ops-readonly orchestrator; do \
		echo "=== $$a ==="; \
		helm template $$a $(CHART_DIR) -f $(CHART_DIR)/examples/fleet/$$a.yaml || exit 1; \
	done

clean:
	rm -rf $(CHART_DIR)/charts $(CHART_DIR)/Chart.lock
