CHART_DIR := .
RELEASE_NAME := test

.PHONY: lint test test-shell template template-all template-fleet clean

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

# Render the three-agent fleet example. Each agent is a different RBAC tier
# and egress posture from the same chart.
template-fleet:
	@for a in reviewer ops-readonly orchestrator; do \
		echo "=== $$a ==="; \
		helm template $$a $(CHART_DIR) -f $(CHART_DIR)/examples/fleet/$$a.yaml || exit 1; \
	done

clean:
	rm -rf $(CHART_DIR)/charts $(CHART_DIR)/Chart.lock
