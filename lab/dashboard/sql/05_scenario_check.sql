-- ¿Se ve el escenario? Tasa de error por categoría, dentro vs fuera de la ventana
-- min 35-45 de la corrida. Se espera ~2x en electronics dentro de la ventana.
-- Nota: los 404 de IDs inexistentes no tienen categoría (category = NULL).
-- Si hubo pruebas antes de la corrida, MIN(timestamp) corre la ventana: descomenta
-- run_start y pon la hora "Inicio de la corrida" que imprime el simulador (UTC).
-- Gráfica sugerida: tabla o barras agrupadas (categoria x ventana).
WITH reqs AS (
  SELECT
    timestamp,
    IFNULL(JSON_VALUE(json_payload.category), '(sin categoria)') AS category,
    JSON_VALUE(json_payload.outcome) AS outcome
  FROM `PROJECT_ID.global._Default._Default`
  WHERE JSON_VALUE(json_payload.message) = 'request_completed'
    AND JSON_VALUE(resource.labels.service_name) = 'orders-api'
),
t0 AS (
  SELECT MIN(timestamp) AS run_start FROM reqs
  -- SELECT TIMESTAMP('2026-10-16T01:15:09Z') AS run_start
)
SELECT
  category,
  IF(TIMESTAMP_DIFF(timestamp, run_start, SECOND) BETWEEN 35 * 60 AND 45 * 60,
     'min 35-45', 'resto') AS ventana,
  COUNT(*) AS requests,
  COUNTIF(outcome = 'client_error') AS client_errors,
  COUNTIF(outcome = 'server_error') AS server_errors,
  ROUND(100 * COUNTIF(outcome != 'success') / COUNT(*), 2) AS pct_error
FROM reqs CROSS JOIN t0
GROUP BY category, ventana
ORDER BY category, ventana
