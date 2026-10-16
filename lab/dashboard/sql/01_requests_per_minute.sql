-- Conteo de solicitudes por minuto (debería verse la campana ~N(30, 10)).
-- Reemplaza la tabla por la salida `log_analytics_view` de terraform.
-- Gráfica sugerida: línea / barras · X = minute · Y = requests.
SELECT
  TIMESTAMP_TRUNC(timestamp, MINUTE) AS minute,
  COUNT(*) AS requests
FROM `PROJECT_ID.global._Default._Default`
WHERE JSON_VALUE(json_payload.message) = 'request_completed'
  AND JSON_VALUE(resource.labels.service_name) = 'orders-api'
GROUP BY minute
ORDER BY minute
