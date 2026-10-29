.PHONY: setup verify reset status logs install_uv uv_init uv_sync uv_update

# Local stack runs on a kind (Kubernetes-in-Docker) cluster. See scripts/.
# Note: use a demo-specific variable name — a generic NAMESPACE is often
# exported by other tooling and would silently override the local target.
KIND_CLUSTER ?= retail-stock-take
LOCAL_NS ?= retail
# Dedicated kubeconfig for the local stack — keeps an ambient KUBECONFIG (e.g. a
# corporate cluster) from redirecting kubectl. Must match scripts/lib.sh.
KIND_KUBECONFIG ?= $(HOME)/.kube/$(KIND_CLUSTER)-config

setup:
	./scripts/setup.sh

verify:
	./scripts/verify.sh

reset:
	./scripts/reset.sh

status:
	KUBECONFIG=$(KIND_KUBECONFIG) kubectl -n $(LOCAL_NS) get pods,svc,ingress

# Tail logs for all app pods (label set by the web-app chart values, W6).
logs:
	KUBECONFIG=$(KIND_KUBECONFIG) kubectl -n $(LOCAL_NS) logs -l app.kubernetes.io/part-of=$(KIND_CLUSTER) --all-containers --tail=200 -f

install_uv:
	curl -LsSf https://astral.sh/uv/install.sh | sh

uv_init:
	cd backend && uv venv

uv_sync:
	cd backend && uv sync

uv_update:
	cd backend && uv lock --upgrade
