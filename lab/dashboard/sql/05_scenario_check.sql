-- ¿Se ve el escenario? Tasa de error por categoría, dentro vs fuera de la ventana
-- min 35-45 de la corrida. Se espera ~2x en electronics dentro de la ventana.
-- Nota: los 404 de IDs inexistentes no tienen categoría (category = NULL).
-- Gráfica sugerida: tabla o barras agrupadas (categoria x ventana).
WITH reqs AS (
  SELECT
    timestamp,
    IFNULL(JSON_VALUE(json_payload.category), '(sin categoría)') AS category,
    JSON_VALUE(json_payload.outcome) AS outcome
  FROM `PROJECT_ID.global._Default._Default`
  WHERE JSON_VALUE(json_payload.message) = 'request_completed'
    AND JSON_VALUE(resource.labels.service_name) = 'orders-api'
),
t0 AS (SELECT MIN(timestamp) AS run_start FROM reqs)
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
