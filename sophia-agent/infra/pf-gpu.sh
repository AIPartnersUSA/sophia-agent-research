#!/usr/bin/env bash
# pf-gpu.sh — port-forward every GPU-backed inference service on the cluster
# to a stable localhost port. Useful for ad-hoc benchmarks, curl-based
# smoke tests, and Jupyter notebooks that need to talk to the same services
# voice-relay / dashboard talk to in-cluster.
#
# Usage:
#   ./infra/pf-gpu.sh              # discover GPU services + forward all
#   ./infra/pf-gpu.sh list         # only print the discovery table; exit
#   NAMESPACE=default ./infra/pf-gpu.sh   # override target namespace
#
# Convention: each service binds to the SAME port locally that it serves
# in-cluster (whisper 8080, kokoro 8122, etc.) so the URLs in
# voice-relay's env vars (WHISPER_URL=http://whisper-inference:8080, …)
# work verbatim if you set them to http://localhost:<port>.
#
# Background `kubectl port-forward` PIDs are tracked in /tmp/pf-gpu.pids
# and torn down on SIGINT (Ctrl-C) or via `./pf-gpu.sh stop`.

set -euo pipefail

NAMESPACE="${NAMESPACE:-multi-agent}"
PID_FILE="/tmp/pf-gpu.pids"
LOG_DIR="/tmp/pf-gpu-logs"

# Cross-namespace observability service. Lives in `monitoring` ns alongside
# Prometheus. Local 3030 -> remote 80 to match the team's documented URL:
#   http://localhost:3030/d/benchmarking-infrastructure/benchmarking-infrastructure
GRAFANA_NS="${GRAFANA_NS:-monitoring}"
GRAFANA_SVC="${GRAFANA_SVC:-infra-prometheus-grafana}"
GRAFANA_LOCAL="${GRAFANA_LOCAL:-3030}"
GRAFANA_REMOTE="${GRAFANA_REMOTE:-80}"

# Curated list of services to forward. Each entry is
#   "svc-name[:local-port]"
# If `:local-port` is omitted, the local port matches the Service's port.
# Override local ports for services that collide (whisper-inference AND
# qwen3-inference both serve on :8080 in-cluster, but obviously can't both
# bind to :8080 on localhost). Convention: collisions use 18xxx so the
# in-cluster port is still recoverable by dropping the leading "1".
# =========================================================================
# READ ME — researcher-facing list (the inference services to talk to)
# =========================================================================
# This list is the "online" inference plane: services that are kept warm by
# the work-hours cron (inference-schedule.yaml) and are the canonical LLM /
# STT / TTS / RAG entry points for ALL downstream consumers (voice-relay,
# sophia-spatial-ai, dashboard, jupyterlab, multi-modal-rag, etc.).
#
# NOT in this list, by design:
#   - qwen3-vl-vllm    — same model as qwen3-inference but on vLLM, only
#                        used by the ingestion pipeline (qwen3-vl-ingest);
#                        scaled manually + only spun up during bulk doc
#                        uploads. Don't research against this — it may not
#                        be running, and even when it is, the request
#                        shape it's tuned for is batch-throughput not
#                        single-prompt latency.
#   - qwen3-vl-ingest  — the doc-ingestion worker, not an inference API.
#
# Future: when KEDA lands + ingest-gpu autoscales on upload-pipeline load
# (see STATUS.md follow-up), `qwen3-vl-vllm` becomes the consolidated
# target and `qwen3-inference` retires. Until then, point research code at
# `qwen3-inference` — it's what voice-relay + sophia + dashboard use today.
KNOWN_GPU_SERVICES=(
  "whisper-inference"             # serves :8080  → local :8080
  # `qwen3-inference` loads Qwen3-VL-8B-Instruct int4 via our custom
  # inference-server image (slurm/inference-deployment.yaml,
  # MODEL_PATH=/models/Qwen3-VL-8B-Instruct). Voice-relay's QWEN3_URL +
  # every other consumer points here. OpenAI-compatible `/v1/chat/completions`.
  "qwen3-inference:18080"         # serves :8080  → local :18080 (collision)
  "kokoro-tts"                    # serves :8122  → local :8122
  "orpheus-tts"                   # serves :8120  → local :8120 (historical, may be gone)
  "sophia-spatial-ai"             # serves :8106  → local :8106
  "voice-relay"                   # serves :8111  → local :8111  (not GPU but useful)
)

require() { command -v "$1" >/dev/null || { echo "missing dep: $1"; exit 1; }; }
require kubectl
require jq

discover_gpu_pods() {
  # Print "namespace/name <tab> gpus" for every Pod requesting nvidia.com/gpu.
  kubectl get pods -A -o json | jq -r '
    .items[]
    | select(any(.spec.containers[]; .resources.requests."nvidia.com/gpu" // empty))
    | "\(.metadata.namespace)/\(.metadata.name)\tgpus=\([.spec.containers[].resources.requests."nvidia.com/gpu" // "0"] | add)\tnode=\(.spec.nodeName // "-")"
  '
}

# Parse "svc[:local-port]" → echoes "svc<TAB>local_port_override_or_empty"
parse_entry() {
  local entry="$1"
  if [[ "$entry" == *:* ]]; then
    printf "%s\t%s\n" "${entry%%:*}" "${entry##*:}"
  else
    printf "%s\t\n" "$entry"
  fi
}

discover_services() {
  # For each KNOWN service name, look up its Service object (remote port +
  # ns) so we don't hardcode the cluster port here — single source of truth
  # is the manifest. Local port comes from the curated list (override or
  # default = remote port).
  for entry in "${KNOWN_GPU_SERVICES[@]}"; do
    IFS=$'\t' read -r svc local_port_override < <(parse_entry "$entry")
    remote_port=$(kubectl get svc "$svc" -n "$NAMESPACE" \
      -o jsonpath='{.spec.ports[0].port}' 2>/dev/null || true)
    [[ -z "$remote_port" ]] && remote_port="-"
    local_port="${local_port_override:-$remote_port}"
    printf "%s/%s\tremote=%s\tlocal=%s\n" \
      "$NAMESPACE" "$svc" "$remote_port" "$local_port"
  done
}

cmd_list() {
  echo "=== GPU-requesting Pods (cluster-wide) ==="
  discover_gpu_pods | column -t
  echo
  echo "=== Curated GPU Services in namespace=$NAMESPACE (port-forward targets) ==="
  discover_services | column -t
}

cmd_stop() {
  if [[ ! -f "$PID_FILE" ]]; then
    echo "no PID file at $PID_FILE — nothing to stop"
    return 0
  fi
  while read -r pid; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done < "$PID_FILE"
  rm -f "$PID_FILE"
  echo "stopped all GPU port-forwards"
}

cmd_start() {
  mkdir -p "$LOG_DIR"
  : > "$PID_FILE"
  trap cmd_stop EXIT INT TERM

  echo "Starting port-forwards (logs: $LOG_DIR/<svc>.log)"
  printf "  %-22s %-8s %-8s %s\n" "SERVICE" "REMOTE" "LOCAL" "URL"
  printf "  %-22s %-8s %-8s %s\n" "----------------------" "------" "------" "---"

  for entry in "${KNOWN_GPU_SERVICES[@]}"; do
    IFS=$'\t' read -r svc local_port_override < <(parse_entry "$entry")

    # Remote port comes from the manifest — single source of truth.
    remote_port=$(kubectl get svc "$svc" -n "$NAMESPACE" \
      -o jsonpath='{.spec.ports[0].port}' 2>/dev/null || true)
    if [[ -z "$remote_port" ]]; then
      printf "  %-22s %-8s %-8s skipped — svc not found in ns=%s\n" \
        "$svc" "-" "-" "$NAMESPACE"
      continue
    fi

    # Local port: explicit override > same as remote.
    local_port="${local_port_override:-$remote_port}"

    # Skip if something already owns this local port (re-run after Ctrl-C,
    # another session forwarding the same svc, etc.).
    if lsof -iTCP:"$local_port" -sTCP:LISTEN -t >/dev/null 2>&1; then
      printf "  %-22s %-8s %-8s skipped — local port already in use\n" \
        "$svc" "$remote_port" "$local_port"
      continue
    fi

    log_file="$LOG_DIR/$svc.log"
    kubectl port-forward -n "$NAMESPACE" "svc/$svc" "$local_port:$remote_port" \
      >"$log_file" 2>&1 &
    pid=$!
    echo "$pid" >> "$PID_FILE"
    printf "  %-22s %-8s %-8s http://localhost:%s   (pid=%d)\n" \
      "$svc" "$remote_port" "$local_port" "$local_port" "$pid"
  done

  # Cross-namespace special case: Grafana (observability) lives in `monitoring`
  # not `multi-agent`. Same lifecycle (PID file, log file, skip if port in use).
  if lsof -iTCP:"$GRAFANA_LOCAL" -sTCP:LISTEN -t >/dev/null 2>&1; then
    printf "  %-22s %-8s %-8s skipped — local port already in use\n" \
      "$GRAFANA_SVC" "$GRAFANA_REMOTE" "$GRAFANA_LOCAL"
  else
    grafana_remote_check=$(kubectl get svc "$GRAFANA_SVC" -n "$GRAFANA_NS" \
      -o jsonpath='{.spec.ports[0].port}' 2>/dev/null || true)
    if [[ -z "$grafana_remote_check" ]]; then
      printf "  %-22s %-8s %-8s skipped — svc not found in ns=%s\n" \
        "$GRAFANA_SVC" "-" "-" "$GRAFANA_NS"
    else
      grafana_log="$LOG_DIR/$GRAFANA_SVC.log"
      kubectl port-forward -n "$GRAFANA_NS" "svc/$GRAFANA_SVC" \
        "$GRAFANA_LOCAL:$GRAFANA_REMOTE" >"$grafana_log" 2>&1 &
      pid=$!
      echo "$pid" >> "$PID_FILE"
      printf "  %-22s %-8s %-8s http://localhost:%s   (pid=%d)\n" \
        "$GRAFANA_SVC" "$GRAFANA_REMOTE" "$GRAFANA_LOCAL" "$GRAFANA_LOCAL" "$pid"
    fi
  fi

  echo
  echo "All forwards running. Press Ctrl-C to tear down, or in another shell:"
  echo "  ./infra/pf-gpu.sh stop"
  echo
  echo "Sanity-check a service:"
  echo "  curl -s http://localhost:18080/health  # qwen3-inference  (LLM — point research here)"
  echo "  curl -s http://localhost:8080/health   # whisper-inference (STT)"
  echo "  curl -s http://localhost:8122/health   # kokoro-tts        (TTS)"
  echo "  curl -s http://localhost:8106/health   # sophia-spatial-ai (RAG)"
  echo "  open http://localhost:3030/d/benchmarking-infrastructure  # Grafana dashboard"
  echo
  echo "Talk to the LLM (OpenAI-compatible chat completions):"
  echo "  curl -sN http://localhost:18080/v1/chat/completions \\"
  echo "    -H 'Content-Type: application/json' \\"
  echo "    -d '{\"model\":\"qwen3\",\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}],\"stream\":true}'"
  echo
  # Hold the foreground so the trap cleans up on Ctrl-C. macOS ships bash
  # 3.2 which lacks `wait -n`, so we poll the PID file: if every recorded
  # PID has died, exit. 2 s cadence is fine — kubectl port-forward dying
  # is a "rare and significant" event, not a hot path.
  while :; do
    sleep 2
    any_alive=0
    while read -r pid; do
      [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && { any_alive=1; break; }
    done < "$PID_FILE"
    if [[ "$any_alive" -eq 0 ]]; then
      echo "all port-forwards exited"
      break
    fi
  done
}

case "${1:-start}" in
  list)  cmd_list ;;
  stop)  cmd_stop ;;
  start) cmd_start ;;
  *)     echo "usage: $0 [start|list|stop]"; exit 1 ;;
esac