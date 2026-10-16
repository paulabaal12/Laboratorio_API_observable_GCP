# Laboratorio: API serverless observable en GCP (CC3106 · UVG)

API de pedidos en **Cloud Run functions**, una hora de tráfico simulado con
errores intencionales y un **dashboard de Cloud Monitoring** que combina
métricas nativas, métricas basadas en logs, SQL de Log Analytics y un panel de logs.

- Enunciado: [docs/Laboratorio_API_observable_GCP.pdf](docs/Laboratorio_API_observable_GCP.pdf)
- Diagrama objetivo: [docs/arquitectura_lab_gcp.webp](docs/arquitectura_lab_gcp.webp)
- Guía del dashboard: [lab/dashboard/GUIA.md](lab/dashboard/GUIA.md)

```
lab/
  infra/       Terraform (copiado del enunciado): función, cuentas de servicio, bucket, Log Analytics
  backend/     main.py (entry point handle) + requirements.txt  ← esto se zipea y despliega
  simulator/   simulator.py + config.json  → genera requests.csv
  dashboard/   métricas de logs (YAML), SQL, dashboard.json, commands.sh, GUIA.md
  tests/       pytest del backend + compare_csv_logs.py (cruce CSV ↔ logs)
```

## API

| Operación | Ruta | Éxito | Errores |
|---|---|---|---|
| Crear pedido | `POST /orders` `{customer_id, customer_tier, category, amount}` | 201 | 400 payload inválido |
| Consultar | `GET /orders/{id}` | 200 | 404 ID inexistente |
| Cancelar | `POST /cancel/{id}` | 200 | 404 · 409 ya cancelado / pedido `digital` ya entregado |

- `customer_tier`: `free | standard | pro` · `category`: `electronics | books | clothing | home | digital` · `0 < amount ≤ 10000`.
- `FAILURE_RATE` → 500 simulado (solo en solicitudes válidas) · `EXTRA_LATENCY_MS` → latencia extra.
- Cada solicitud escribe **una línea JSON** en stdout: `severity`, `message="request_completed"`,
  `request_id` (header `X-Request-ID`), `endpoint`, `status_code`, `outcome`, `error_type`,
  `latency_ms`, `customer_tier`, `category`, `amount`, `order_id`.
- El `order_id` es autocontenido (tier-categoría-centavos-nonce-checksum), así que cualquier
  instancia lo resuelve aunque la memoria no se comparta entre instancias.
  El "ya cancelado" sí vive en memoria de cada instancia; el 409 determinista es cancelar un `digital`.

## Requisitos
- Python 3.13, `gcloud` y Terraform ≥ 1.5. Si no tienes Terraform instalado, el repo usa
  un binario local en `.tools/terraform.exe` (ignorado por git):
  `TF=./.tools/terraform.exe` (o `TF=terraform` si lo tienes en el PATH).
- Git Bash en Windows para los comandos de abajo.

## Correr el lab (orden exacto)

```bash
# 0) Entorno local (una vez)
python -m venv .venv
.venv/Scripts/python -m pip install -r lab/backend/requirements.txt -r lab/simulator/requirements.txt pytest
.venv/Scripts/python -m pytest lab/tests -q            # 11 pruebas: 201/200/400/404/405/409/500 + formato del log
TF=./.tools/terraform.exe

# 1) Autenticación
gcloud auth login
gcloud auth application-default login
export PROJECT_ID="tu-proyecto"                         # ← tu project_id real
gcloud config set project "$PROJECT_ID"

# 2) Variables de Terraform: edita lab/infra/terraform.tfvars (project_id real)
#    y evita commitearlo por accidente:
git update-index --skip-worktree lab/infra/terraform.tfvars

# 3) Infraestructura  (si el primer apply falla en el build, espera 1 min y repite)
$TF -chdir=lab/infra init
$TF -chdir=lab/infra plan
$TF -chdir=lab/infra apply

# 4) URL de la función → config.json
URL=$($TF -chdir=lab/infra output -raw function_url)
.venv/Scripts/python -c "import json,sys;p='lab/simulator/config.json';c=json.load(open(p));c['target_url']=sys.argv[1];json.dump(c,open(p,'w'),indent=2)" "$URL"
git update-index --skip-worktree lab/simulator/config.json

# 5) Métricas basadas en logs (ANTES del simulador) y dashboard
bash lab/dashboard/commands.sh check                   # confirma que llegan los logs
bash lab/dashboard/commands.sh metrics
bash lab/dashboard/commands.sh dashboard

# 6) Simulador: 60 minutos reales (6000 solicitudes, pico ≈ 4 req/s)
.venv/Scripts/python lab/simulator/simulator.py --dry-run   # opcional: revisa el plan
.venv/Scripts/python lab/simulator/simulator.py             # escribe lab/simulator/requests.csv

# 7) Paneles SQL: lab/dashboard/GUIA.md, paso 5 (Log Analytics → Add to dashboard)
$TF -chdir=lab/infra output log_analytics_view

# 8) Limpieza
bash lab/dashboard/commands.sh cleanup                 # métricas de logs + dashboard
$TF -chdir=lab/infra destroy
```

### Flags del simulador
| Flag | Uso |
|---|---|
| `--time-scale 60` | comprime la hora: 60 = todo en 1 minuto (solo para pruebas) |
| `--dry-run` | genera el plan (`requests_plan.csv`) sin HTTP e imprime μ, σ y el pico |
| `--limit 200` | genera solo 200 solicitudes con la misma distribución |
| `--url http://127.0.0.1:8080` | sobrescribe `target_url` |
| `--out archivo.csv` | cambia el CSV de salida |

`requests.csv`: `request_id, scheduled_min, scheduled_at, sent_at, send_lag_ms, operation,
intended_event, detail, method, path, category, customer_tier, amount, expected_status,
status_code, client_latency_ms, error`.

## Prueba local (sin GCP)

```bash
# Terminal 1: la función en local (PYTHONDONTWRITEBYTECODE evita __pycache__ en lab/backend)
cd lab/backend
FAILURE_RATE=0.02 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
  ../../.venv/Scripts/functions-framework --target handle --source main.py \
  --host 127.0.0.1 --port 8080 > ../../backend_local.log

# Terminal 2: 500 solicitudes en ~6 min y cruce CSV ↔ logs
.venv/Scripts/python lab/simulator/simulator.py --url http://127.0.0.1:8080 --limit 500 --time-scale 10
.venv/Scripts/python lab/tests/compare_csv_logs.py lab/simulator/requests.csv backend_local.log
```

Usa `127.0.0.1` y no `localhost`: en Windows, `localhost` intenta IPv6 primero y suma ~300 ms por conexión.
El servidor de desarrollo local se satura arriba de ~50 req/s; con `--time-scale` alto
la espera aparece en `send_lag_ms`. En Cloud Run eso no pasa a 4 req/s.

## Skills de Claude Code (alcance proyecto)
`.claude/skills/` contiene una selección de [google/skills](https://github.com/google/skills)
(gcloud, Cloud Run, Cloud Build, auth, Logging, Monitoring) y las skills de
[obra/superpowers](https://github.com/obra/superpowers). Su hook de inicio está en
`.claude/hooks/` y se registra en `.claude/settings.json`. Las licencias están en `.claude/licenses/`.
