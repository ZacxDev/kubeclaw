CHART_DIR := .
RELEASE_NAME := test

.PHONY: lint test template template-all clean

lint:
	helm lint $(CHART_DIR) --set agentName=test

test:
	helm unittest $(CHART_DIR)

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

clean:
	rm -rf $(CHART_DIR)/charts $(CHART_DIR)/Chart.lock
