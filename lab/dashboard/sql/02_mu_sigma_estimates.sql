-- μ y σ estimados de los minutos de llegada (comparar con config.json: μ=30, σ=10).
-- El minuto de llegada se mide desde el inicio de la corrida. Por defecto se usa
-- la primera solicitud (MIN(timestamp)), que llega ~0.1 min después del inicio real.
-- Para mayor precisión, descomenta run_start y pon la hora "Inicio de la corrida"
-- que imprime el simulador (UTC). Ajusta el selector de tiempo a la ventana de la corrida.
-- Gráfica sugerida: tabla / scorecard.
WITH reqs AS (
  SELECT timestamp
  FROM `PROJECT_ID.global._Default._Default`
  WHERE JSON_VALUE(json_payload.message) = 'request_completed'
    AND JSON_VALUE(resource.labels.service_name) = 'orders-api'
),
t0 AS (
  SELECT MIN(timestamp) AS run_start FROM reqs
  -- SELECT TIMESTAMP('2026-10-16T01:15:09Z') AS run_start   -- inicio de la corrida del 15/10 (19:15 CST)
),
arrivals AS (
  SELECT TIMESTAMP_DIFF(r.timestamp, t0.run_start, MILLISECOND) / 60000.0 AS arrival_min
  FROM reqs AS r CROSS JOIN t0
  WHERE r.timestamp >= t0.run_start
)
SELECT
  COUNT(*)                         AS n,
  ROUND(AVG(arrival_min), 2)       AS mu_estimada_min,
  ROUND(STDDEV(arrival_min), 2)    AS sigma_estimada_min,
  ROUND(MIN(arrival_min), 2)       AS primer_min,
  ROUND(MAX(arrival_min), 2)       AS ultimo_min
FROM arrivals
