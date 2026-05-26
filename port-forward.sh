#!/bin/bash
# Port-forward all benchmarking services from EKS to localhost.
#
# Usage:
#   ./scripts/port-forward-benchmarking.sh          # all services
#   ./scripts/port-forward-benchmarking.sh --no-gpu # skip GPU services (colpali/colqwen2)
#
# Stop all: Ctrl-C (or: kill $(jobs -p))

set -euo pipefail

NO_GPU=false
[[ "${1:-}" == "--no-gpu" ]] && NO_GPU=true

NS="multi-agent"
PIDS=()

cleanup() {
    echo -e "\nStopping port-forwards..."
    for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
    wait 2>/dev/null
    echo "Done."
}
trap cleanup EXIT INT TERM

forward() {
    local svc="$1"; shift
    kubectl port-forward -n "$NS" "svc/$svc" "$@" &
    PIDS+=($!)
    echo "  $svc → $*"
}

echo "Starting port-forwards (namespace: $NS)..."
forward qdrant         6333:6333 6334:6334
forward elasticsearch  9200:9200
forward bge-embedding  8112:8112
forward faiss          8103:8103

if [[ "$NO_GPU" == "false" ]]; then
    forward colpali    8110:8110
    forward colqwen2   8111:8111
fi

echo ""
echo "Ready. Services available on localhost."
echo "Press Ctrl-C to stop all."
wait