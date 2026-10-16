-- Resumen de la corrida: solicitudes por outcome, status y tipo de error.
-- Contrastar con requests.csv (verdad de referencia del simulador).
-- Gráfica sugerida: tabla o barras horizontales.
SELECT
  JSON_VALUE(json_payload.outcome)          AS outcome,
  JSON_VALUE(json_payload.status_code)      AS status_code,
  IFNULL(JSON_VALUE(json_payload.error_type), '-') AS error_type,
  JSON_VALUE(json_payload.endpoint)         AS endpoint,
  COUNT(*)                                  AS requests,
  ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM `PROJECT_ID.global._Default._Default`
WHERE JSON_VALUE(json_payload.message) = 'request_completed'
  AND JSON_VALUE(resource.labels.service_name) = 'orders-api'
GROUP BY outcome, status_code, error_type, endpoint
ORDER BY requests DESC
