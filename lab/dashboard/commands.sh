#!/usr/bin/env bash
# Comandos gcloud para las métricas basadas en logs y el dashboard.
# Corre UN paso a la vez, desde la raíz del repo (Git Bash en Windows):
#
#   export PROJECT_ID="tu-proyecto"          # obligatorio
#   export FUNCTION_NAME="orders-api"        # opcional, igual que en terraform.tfvars
#
#   bash lab/dashboard/commands.sh check      # solo lectura: confirma que llegan los logs
#   bash lab/dashboard/commands.sh metrics    # CREA las 2 métricas basadas en logs (antes del simulador)
#   bash lab/dashboard/commands.sh dashboard  # CREA el dashboard desde dashboard.json
#   bash lab/dashboard/commands.sh list       # solo lectura: lista métricas y dashboards
#   bash lab/dashboard/commands.sh cleanup    # BORRA métricas y dashboard (terraform destroy no los borra)
set -euo pipefail

: "${PROJECT_ID:?Define PROJECT_ID, p. ej. export PROJECT_ID=mi-proyecto}"
FUNCTION_NAME="${FUNCTION_NAME:-orders-api}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

METRICS=(orders_requests_by_outcome orders_amount)
DASHBOARD_NAME="Orders API - observabilidad (CC3106)"

# Sustituye el nombre de la función si no es el default.
render() { sed "s/orders-api/${FUNCTION_NAME}/g" "$1" > "$TMP/$(basename "$1")"; echo "$TMP/$(basename "$1")"; }

case "${1:-}" in
  check)
    gcloud logging read \
      "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${FUNCTION_NAME}\" AND jsonPayload.message=\"request_completed\"" \
      --project="$PROJECT_ID" --limit=3 --freshness=1h \
      --format="table(timestamp, severity, resource.type, jsonPayload.endpoint, jsonPayload.status_code, jsonPayload.request_id)"
    ;;
  metrics)
    for m in "${METRICS[@]}"; do
      gcloud logging metrics create "$m" --project="$PROJECT_ID" \
        --config-from-file="$(render "$HERE/metrics/$m.yaml")"
    done
    ;;
  dashboard)
    gcloud monitoring dashboards create --project="$PROJECT_ID" \
      --config-from-file="$(render "$HERE/dashboard.json")"
    ;;
  list)
    gcloud logging metrics list --project="$PROJECT_ID" --format="table(name, metricDescriptor.valueType)"
    gcloud monitoring dashboards list --project="$PROJECT_ID" --format="table(name, displayName)"
    ;;
  cleanup)
    for m in "${METRICS[@]}"; do
      gcloud logging metrics delete "$m" --project="$PROJECT_ID" --quiet || true
    done
    for d in $(gcloud monitoring dashboards list --project="$PROJECT_ID" \
                 --filter="displayName=\"${DASHBOARD_NAME}\"" --format="value(name)"); do
      gcloud monitoring dashboards delete "$d" --project="$PROJECT_ID" --quiet
    done
    ;;
  *)
    sed -n '2,12p' "$0"
    exit 1
    ;;
esac
