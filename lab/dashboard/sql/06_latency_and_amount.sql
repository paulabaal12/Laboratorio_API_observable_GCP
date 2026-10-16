-- Latencia del backend (latency_ms del log) y monto por categoría.
-- Complementa la latencia nativa: aquí es tiempo dentro del handler, sin red ni arranque en frío.
-- Gráfica sugerida: tabla o barras · X = category.
SELECT
  IFNULL(JSON_VALUE(json_payload.category), '(sin categoría)') AS category,
  COUNT(*) AS requests,
  APPROX_QUANTILES(SAFE_CAST(JSON_VALUE(json_payload.latency_ms) AS FLOAT64), 100)[OFFSET(50)] AS latency_p50_ms,
  APPROX_QUANTILES(SAFE_CAST(JSON_VALUE(json_payload.latency_ms) AS FLOAT64), 100)[OFFSET(95)] AS latency_p95_ms,
  ROUND(AVG(IF(JSON_VALUE(json_payload.endpoint) = 'POST /orders'
               AND JSON_VALUE(json_payload.outcome) = 'success',
               SAFE_CAST(JSON_VALUE(json_payload.amount) AS FLOAT64), NULL)), 2) AS avg_amount_created
FROM `PROJECT_ID.global._Default._Default`
WHERE JSON_VALUE(json_payload.message) = 'request_completed'
  AND JSON_VALUE(resource.labels.service_name) = 'orders-api'
GROUP BY category
ORDER BY requests DESC
