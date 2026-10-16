-- Errores por outcome y minuto (client_error vs server_error).
-- Debe notarse el escenario double_errors (electronics, min 35-45 de la corrida).
-- Gráfica sugerida: barras apiladas · X = minute · Y = errors · serie = outcome.
SELECT
  TIMESTAMP_TRUNC(timestamp, MINUTE) AS minute,
  JSON_VALUE(json_payload.outcome) AS outcome,
  COUNT(*) AS errors
FROM `PROJECT_ID.global._Default._Default`
WHERE JSON_VALUE(json_payload.message) = 'request_completed'
  AND JSON_VALUE(resource.labels.service_name) = 'orders-api'
  AND JSON_VALUE(json_payload.outcome) != 'success'
GROUP BY minute, outcome
ORDER BY minute, outcome
