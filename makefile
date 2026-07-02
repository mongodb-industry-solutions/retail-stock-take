.PHONY: setup verify reset status logs install_uv uv_init uv_sync uv_update

# Local stack runs on a kind (Kubernetes-in-Docker) cluster. See scripts/.
KIND_CLUSTER ?= retail-stock-take
NAMESPACE ?= retail

setup:
	./scripts/setup.sh

verify:
	./scripts/verify.sh

reset:
	./scripts/reset.sh

status:
	kubectl -n $(NAMESPACE) get pods,svc,ingress

# Tail logs for all app pods (label set by the web-app chart values, W6).
logs:
	kubectl -n $(NAMESPACE) logs -l app.kubernetes.io/part-of=$(KIND_CLUSTER) --all-containers --tail=200 -f

install_uv:
	curl -LsSf https://astral.sh/uv/install.sh | sh

uv_init:
	cd backend && uv venv

uv_sync:
	cd backend && uv sync

uv_update:
	cd backend && uv lock --upgrade
