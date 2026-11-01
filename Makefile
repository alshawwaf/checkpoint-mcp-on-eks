# Convenience targets for contributors (the CLI itself is cross-platform: python -m chkpmcpeks).
.PHONY: check lint test chart terraform

check: lint test chart terraform

lint:
	ruff check .

test:
	pytest -q

chart:
	helm lint charts/checkpoint-mcp -f charts/checkpoint-mcp/ci/test-values.yaml --strict
	helm template t charts/checkpoint-mcp -n chkp-mcp -f charts/checkpoint-mcp/ci/test-values.yaml > /dev/null

terraform:
	cd terraform/build && terraform fmt -check && terraform init -backend=false -input=false >/dev/null && terraform validate
	cd terraform/platform && terraform fmt -check && terraform init -backend=false -input=false >/dev/null && terraform validate
