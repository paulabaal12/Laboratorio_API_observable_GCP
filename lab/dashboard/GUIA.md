# Guía: dashboard de Cloud Monitoring

Objetivo: **un solo dashboard** que combine las cuatro fuentes del diagrama
(`docs/arquitectura_lab_gcp.webp`):

| Panel | Fuente | Dónde se define |
|---|---|---|
| Solicitudes por minuto | métrica nativa `run.googleapis.com/request_count` | `dashboard.json` |
| Latencia p50 / p95 | métrica nativa `run.googleapis.com/request_latencies` | `dashboard.json` |
| Instancias activas | métrica nativa `run.googleapis.com/container/instance_count` | `dashboard.json` |
| Errores por outcome | métrica de logs `orders_requests_by_outcome` | `metrics/*.yaml` + `dashboard.json` |
| Errores por tipo/endpoint | métrica de logs `orders_requests_by_outcome` | `dashboard.json` |
| Histograma de amount | métrica de logs `orders_amount` (distribución) | `metrics/*.yaml` + `dashboard.json` |
| Panel de logs (`severity >= WARNING`) | Cloud Logging | `dashboard.json` |
| μ y σ estimados, conteo por minuto, errores por outcome | SQL de Log Analytics | `sql/*.sql` (se agregan desde la consola) |

> Todos los comandos asumen Git Bash en la raíz del repo y `export PROJECT_ID=...`.
> Si cambiaste `function_name`, haz también `export FUNCTION_NAME=...` (el script lo sustituye en los YAML/JSON).

---

## Paso 0 — Requisitos
- `terraform apply` ya terminó y la función responde.
- Tienes el rol `roles/logging.configWriter` y `roles/monitoring.editor` (o Owner).

## Paso 1 — Confirmar que llegan los logs (solo lectura)
Manda una solicitud de prueba y revisa que el log aparezca como `cloud_run_revision`:

```bash
URL=$(terraform -chdir=lab/infra output -raw function_url)   # o .tools/terraform.exe
curl -s -X POST "$URL/orders" -H "X-Request-ID: smoke-1" -H "Content-Type: application/json" \
  -d '{"customer_id":"c-1","customer_tier":"pro","category":"books","amount":12.5}'
bash lab/dashboard/commands.sh check
```

Debe salir una fila con `resource.type = cloud_run_revision` y `request_id = smoke-1`
(puede tardar ~1 min). Si `resource.type` sale distinto, cambia el filtro en
`metrics/*.yaml` y `dashboard.json` antes de seguir.

## Paso 2 — Crear las métricas basadas en logs (**antes** del simulador)
Las métricas basadas en logs **no cuentan logs anteriores a su creación**.

```bash
bash lab/dashboard/commands.sh metrics
bash lab/dashboard/commands.sh list
```

Crea:
- `orders_requests_by_outcome` — contador con etiquetas `outcome`, `endpoint`, `error_type`, `category`.
- `orders_amount` — distribución de `amount` (solo `POST /orders` exitosos), etiquetas `category`, `customer_tier`.

Alternativa en consola: *Logging → Log-based metrics → Create metric*, copiando
filtro, etiquetas y extractor de cada YAML.

## Paso 3 — Crear el dashboard desde JSON
```bash
bash lab/dashboard/commands.sh dashboard
```
Alternativa en consola: *Monitoring → Dashboards → Create dashboard → ⋮ → JSON editor*,
pega `dashboard.json` y guarda.

Los paneles de métricas de logs saldrán vacíos hasta que existan datos (y la
métrica puede tardar unos minutos en aparecer después de la primera solicitud).

## Paso 4 — Correr el simulador
Ver README (sección *Correr el lab*). Dura 60 minutos; deja la laptop despierta.
Anota la hora **"Inicio de la corrida"** que imprime el simulador (UTC).

## Paso 5 — Agregar los paneles SQL (Log Analytics)
Los gráficos de Log Analytics se agregan al dashboard desde la consola:

1. Abre la URL del output `log_analytics_console` (*Logging → Log Analytics*).
2. Pega una consulta de `sql/` y reemplaza `PROJECT_ID.global._Default._Default`
   por el output `log_analytics_view` (incluye los backticks).
3. Ajusta el selector de tiempo para cubrir **solo** la corrida (p. ej. *Last 2 hours*
   o un rango personalizado). Si hubo pruebas antes, en `02_mu_sigma_estimates.sql`
   descomenta `run_start` y pon la hora de inicio del simulador.
4. *Run query* → pestaña **Chart** → elige el tipo de gráfico sugerido en el comentario.
5. **Save → Add to dashboard** → elige *Orders API - observabilidad (CC3106)*.

| Archivo | Pregunta que responde | Gráfico |
|---|---|---|
| `01_requests_per_minute.sql` | ¿Se ve la campana N(30, 10)? | línea / barras |
| `02_mu_sigma_estimates.sql` | μ y σ estimados vs config (30 / 10) | tabla |
| `03_errors_by_outcome_per_minute.sql` | ¿Cuándo hubo errores y de qué tipo? | barras apiladas |
| `04_outcome_summary.sql` | Resumen por status / error_type / endpoint | tabla |
| `05_scenario_check.sql` | ¿Se duplicaron los errores de electronics en min 35–45? | tabla |
| `06_latency_and_amount.sql` | Latencia del handler y monto medio por categoría | tabla |

Mínimo para cumplir el diagrama: **01, 02 y 03**. 04–06 sirven para el análisis.

## Paso 6 — Acomodar y validar
- Arrastra los paneles SQL para que queden como en el diagrama (μ/σ abajo a la izquierda).
- Rango del dashboard: la hora de la corrida.
- Qué deberías ver:
  - Solicitudes/min: campana con pico ≈ 240–275/min cerca del minuto 30.
  - Latencia: p95 alto al inicio (arranque en frío), luego estable.
  - Instancias activas: sube y baja con la campana.
  - Errores: más altos en el pico; joroba extra en min 35–45 (escenario).
  - μ ≈ 30 y σ ≈ 10 (el plan con seed 42 da μ = 29.91, σ = 9.88).
- Contrasta con `lab/simulator/requests.csv` (verdad de referencia): cada
  `request_id` del CSV debe aparecer en los logs con el mismo `status_code`.

## Paso 7 — Limpieza
`terraform destroy` **no borra** las métricas de logs ni el dashboard (se crearon con gcloud):
```bash
bash lab/dashboard/commands.sh cleanup
```

## Notas
- Log Analytics en `_Default` es un upgrade permanente (lo indica `main.tf`).
- Los 404 por IDs inexistentes no tienen `category` en el log (el ID no existe),
  así que en los cortes por categoría aparecen como `(sin categoría)`.
- El escenario `double_errors` duplica la probabilidad de **errores intencionales del
  simulador** (4xx) para `electronics` en min 35–45; los 500 dependen solo de `FAILURE_RATE`.
