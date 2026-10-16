# API serverless observable en GCP — Plan de implementación

> **Para agentes:** usar superpowers:executing-plans para ejecutar tarea por tarea.

**Goal:** API de pedidos en Cloud Run functions + simulador de 1 h de tráfico + dashboard de Cloud Monitoring, según `docs/Laboratorio_API_observable_GCP.pdf`.

**Architecture:** Terraform (copiado del enunciado) despliega `lab/backend` como Cloud Run function `handle`. El backend escribe una línea JSON por solicitud en stdout; Cloud Logging la indexa (Log Analytics en `_Default`). El simulador dispara N solicitudes con llegadas ~N(μ, σ) y deja `requests.csv` como verdad de referencia. El dashboard combina métricas nativas, métricas basadas en logs, SQL y un panel de logs.

**Tech Stack:** Python 3.13, functions-framework, numpy, httpx (async), pytest, Terraform ≥ 1.5 (provider google ≥ 6), gcloud.

**Spec:** `docs/Laboratorio_API_observable_GCP.pdf`, `docs/arquitectura_lab_gcp.webp`

## Restricciones globales
- `apply`/`destroy`/`gcloud ... create|delete` solo con OK del usuario.
- Sin project_id real ni credenciales en archivos versionados.
- `lab/infra/*.tf` = copia literal del enunciado.

## Decisiones de diseño
- **IDs autocontenidos.** Con `concurrency = 1` y autoscaling hay varias instancias, y la memoria no se comparte entre ellas. El `order_id` codifica tier/categoría/monto + checksum, así cualquier instancia puede resolver un GET/cancel válido. Un ID mal formado o con checksum incorrecto responde 404.
- **409 determinista.** Los pedidos `digital` se entregan al crearse, así que cancelarlos es imposible y devuelve 409 en cualquier instancia. Cancelar dos veces devuelve 409 solo si cae en la misma instancia (best effort).
- **Truncamiento a [0, 60]** por rechazo: se redibujan las muestras fuera de rango, así que es una normal truncada real y no se acumulan muestras en los bordes.
- **Fallas simuladas** (`FAILURE_RATE`): se aplican después de validar, antes del cambio de estado. Solo afectan solicitudes válidas.
- Los tests viven en `lab/tests/`, fuera de `lab/backend/`, para no subirlos en el zip de la función.

## Tareas
- [ ] 1. Scaffolding: `.gitignore`, `lab/infra/*` literal, `terraform fmt/validate`.
- [ ] 2. Backend + tests (200/201/400/404/409/500 y formato del log).
- [ ] 3. Simulador (`--dry-run`, `--limit`, `--time-scale`) + prueba e2e local contra functions-framework; cruce CSV ↔ logs.
- [ ] 4. `lab/dashboard/`: métricas basadas en logs (YAML), SQL, `dashboard.json`, `commands.sh` y `GUIA.md`.
- [ ] 5. README raíz con el orden completo de comandos.
