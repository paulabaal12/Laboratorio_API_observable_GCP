"""Cruza requests.csv (lo que envió el simulador) con los logs JSON del backend.

Uso:
    python lab/tests/compare_csv_logs.py lab/simulator/requests.csv backend.log

backend.log es el stdout de functions-framework en local (una línea JSON por
solicitud). Verifica que cada request_id del CSV tenga su línea de log, que el
status coincida y que solo los 500 simulados se desvíen del status esperado.
"""

import csv
import json
import sys
from collections import Counter

REQUIRED = {"severity", "message", "request_id", "endpoint", "status_code", "outcome",
            "error_type", "latency_ms", "customer_tier", "category", "amount"}
SEVERITY = {"success": "INFO", "client_error": "WARNING", "server_error": "ERROR"}


def main(csv_path: str, log_path: str) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # consola de Windows (cp1252)
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    logs = {}
    problems = []
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if line.startswith("{"):
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    problems.append(f"línea {n} del log no es un JSON válido")
                    continue
                if entry.get("message") == "request_completed":
                    logs[entry["request_id"]] = entry

    unexpected = Counter()
    for row in rows:
        log = logs.get(row["request_id"])
        if log is None:
            problems.append(f"sin log: {row['request_id']}")
            continue
        if missing := REQUIRED - log.keys():
            problems.append(f"{row['request_id']}: faltan campos {missing}")
        if str(log["status_code"]) != row["status_code"]:
            problems.append(f"{row['request_id']}: csv={row['status_code']} log={log['status_code']}")
        if SEVERITY[log["outcome"]] != log["severity"]:
            problems.append(f"{row['request_id']}: severity {log['severity']} no cuadra con {log['outcome']}")
        if row["expected_status"] and row["status_code"] != row["expected_status"]:
            unexpected[(row["intended_event"], row["expected_status"], row["status_code"])] += 1

    print(f"CSV: {len(rows)} filas · logs request_completed: {len(logs)} · cruzadas: {sum(r['request_id'] in logs for r in rows)}")
    print("status en CSV:", dict(Counter(r["status_code"] for r in rows)))
    print("outcome en logs:", dict(Counter(l["outcome"] for l in logs.values())))
    print("eventos intencionados:", dict(Counter(r["intended_event"] for r in rows)))
    print("desvíos esperado→real (evento, esperado, real):", dict(unexpected) or "ninguno")
    non_500 = {k: v for k, v in unexpected.items() if k[2] != "500"}
    if non_500:
        problems.append(f"desvíos que no son 500 simulados: {non_500}")
    for p in problems[:20]:
        print("PROBLEMA:", p)
    print("OK" if not problems else f"{len(problems)} problemas")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
