"""Simulador de tráfico para la API de pedidos.

Genera n_requests instantes ~ N(mu_min, sigma_min) truncada a [0, 60] minutos
(numpy Generator.normal con seed; las muestras fuera de rango se redibujan) y
dispara cada solicitud en su instante sin esperar a la anterior
(asyncio + httpx.AsyncClient). Escribe requests.csv con una fila por solicitud.

Uso:
    python simulator.py                         # corrida real de 60 min
    python simulator.py --time-scale 60         # 60 min comprimidos en 1 min
    python simulator.py --dry-run               # solo genera el plan, sin HTTP
    python simulator.py --limit 200 --time-scale 120 --url http://localhost:8080
"""

import argparse
import asyncio
import csv
import json
import random
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np

HERE = Path(__file__).resolve().parent
WINDOW_MIN = 60.0

TIERS = ["free", "standard", "pro"]
TIER_P = [0.5, 0.35, 0.15]
CATEGORIES = ["electronics", "books", "clothing", "home", "digital"]
CATEGORY_P = [0.30, 0.20, 0.20, 0.15, 0.15]
# Monto típico por categoría (USD); el monto real es base * lognormal(0, 0.5).
AMOUNT_BASE = {"electronics": 250.0, "books": 25.0, "clothing": 60.0, "home": 90.0, "digital": 15.0}

VALID_OPS = ["create", "get", "cancel"]
VALID_OPS_P = [0.60, 0.25, 0.15]
INVALID_EVENTS = ["invalid_payload", "nonexistent_get", "nonexistent_cancel", "impossible_cancel"]
INVALID_EVENTS_P = [0.40, 0.20, 0.15, 0.25]
PAYLOAD_DEFECTS = ["missing_customer_id", "unknown_tier", "unknown_category", "negative_amount",
                   "amount_as_string", "not_json"]

SCENARIO_FACTORS = {"double_errors": 2.0}

EXPECTED_STATUS = {
    ("create", "valid"): 201, ("get", "valid"): 200, ("cancel", "valid"): 200,
    ("create", "invalid_payload"): 400,
    ("get", "nonexistent_get"): 404, ("cancel", "nonexistent_cancel"): 404,
    ("cancel", "impossible_cancel"): 409,
}

CSV_FIELDS = [
    "request_id", "scheduled_min", "scheduled_at", "sent_at", "send_lag_ms",
    "operation", "intended_event", "detail", "method", "path",
    "category", "customer_tier", "amount", "expected_status",
    "status_code", "client_latency_ms", "error",
]


@dataclass
class Planned:
    index: int
    scheduled_min: float
    operation: str           # create | get | cancel
    intended_event: str      # valid | invalid_payload | nonexistent_get | ...
    category: str
    customer_tier: str
    amount: float
    customer_id: str
    detail: str = ""         # variante del error (p. ej. negative_amount)
    in_scenario: bool = False


@dataclass
class Pools:
    """IDs reales devueltos por la API, para operaciones get/cancel válidas."""
    created: dict = field(default_factory=lambda: {c: [] for c in CATEGORIES})
    cancelable: dict = field(default_factory=lambda: {c: [] for c in CATEGORIES if c != "digital"})


# --------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for key in ("target_url", "n_requests", "mu_min", "sigma_min", "invalid_share", "seed"):
        if key not in cfg:
            sys.exit(f"config.json: falta la clave {key!r}")
    for sc in cfg.get("scenarios", []):
        if sc.get("effect") not in SCENARIO_FACTORS:
            sys.exit(f"config.json: efecto de escenario desconocido {sc.get('effect')!r}")
    return cfg


def arrival_minutes(rng: np.random.Generator, n: int, mu: float, sigma: float) -> np.ndarray:
    """n instantes ~ N(mu, sigma) truncada a [0, 60] por rechazo, ordenados."""
    out = np.empty(0)
    while out.size < n:
        draw = rng.normal(mu, sigma, size=max(2 * (n - out.size), 64))
        out = np.concatenate([out, draw[(draw >= 0) & (draw <= WINDOW_MIN)]])
    return np.sort(out[:n])


def error_factor(minute: float, category: str, scenarios: list[dict]) -> tuple[float, bool]:
    factor, hit = 1.0, False
    for sc in scenarios:
        if sc["start_min"] <= minute < sc["end_min"] and sc.get("category") in (None, category):
            factor *= SCENARIO_FACTORS[sc["effect"]]
            hit = True
    return factor, hit


def build_plan(cfg: dict, n: int) -> list[Planned]:
    rng = np.random.default_rng(cfg["seed"])
    minutes = arrival_minutes(rng, n, cfg["mu_min"], cfg["sigma_min"])
    scenarios = cfg.get("scenarios", [])
    plan = []
    for i, minute in enumerate(minutes):
        category = str(rng.choice(CATEGORIES, p=CATEGORY_P))
        tier = str(rng.choice(TIERS, p=TIER_P))
        amount = round(float(AMOUNT_BASE[category] * rng.lognormal(0.0, 0.5)), 2)
        customer_id = f"c-{int(rng.integers(1, 2000)):04d}"
        factor, in_scenario = error_factor(float(minute), category, scenarios)
        detail = ""

        if rng.random() < min(1.0, cfg["invalid_share"] * factor):
            event = str(rng.choice(INVALID_EVENTS, p=INVALID_EVENTS_P))
            operation = {"invalid_payload": "create", "nonexistent_get": "get"}.get(event, "cancel")
            if event == "invalid_payload":
                detail = str(rng.choice(PAYLOAD_DEFECTS))
        else:
            event = "valid"
            operation = str(rng.choice(VALID_OPS, p=VALID_OPS_P))
            if operation == "cancel" and category == "digital":
                # Cancelar un digital siempre es 409; un cancel válido usa otra categoría.
                category = str(rng.choice(CATEGORIES[:-1]))

        plan.append(Planned(i, round(float(minute), 4), operation, event, category, tier,
                            amount, customer_id, detail, in_scenario))
    return plan


# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------

def fake_order_id(rnd: random.Random) -> str:
    return f"ord-{rnd.choice(TIERS)}-{rnd.choice(CATEGORIES)}-{rnd.randint(100, 99999)}-{rnd.getrandbits(32):08x}-000000"


def payload_for(p: Planned) -> dict:
    return {"customer_id": p.customer_id, "customer_tier": p.customer_tier,
            "category": p.category, "amount": p.amount}


def broken_payload(p: Planned):
    body = payload_for(p)
    match p.detail:
        case "missing_customer_id":
            body.pop("customer_id")
        case "unknown_tier":
            body["customer_tier"] = "platinum"
        case "unknown_category":
            body["category"] = "weapons"
        case "negative_amount":
            body["amount"] = -abs(p.amount)
        case "amount_as_string":
            body["amount"] = str(p.amount)
        case "not_json":
            return None
    return body


def pick(ids: list, rnd: random.Random, remove: bool = False):
    if not ids:
        return None
    i = rnd.randrange(len(ids))
    return ids.pop(i) if remove else ids[i]


def resolve(p: Planned, pools: Pools, rnd: random.Random) -> tuple[str, str, dict, str, str]:
    """Decide la solicitud HTTP concreta en el instante de envío.

    Devuelve (method, path, kwargs, operation, intended_event). Si aún no hay
    pedidos reales para un get/cancel (inicio de la corrida), cae a un create
    válido y lo registra así en el CSV.
    """
    if p.intended_event == "invalid_payload":
        body = broken_payload(p)
        if body is None:
            return "POST", "/orders", {"content": b"{not json", "headers": {"Content-Type": "application/json"}}, "create", p.intended_event
        return "POST", "/orders", {"json": body}, "create", p.intended_event
    if p.intended_event == "nonexistent_get":
        return "GET", f"/orders/{fake_order_id(rnd)}", {}, "get", p.intended_event
    if p.intended_event == "nonexistent_cancel":
        return "POST", f"/cancel/{fake_order_id(rnd)}", {}, "cancel", p.intended_event
    if p.intended_event == "impossible_cancel":
        order_id = pick(pools.created["digital"], rnd)
        if order_id:
            return "POST", f"/cancel/{order_id}", {}, "cancel", p.intended_event
        return "POST", "/orders", {"json": payload_for(p)}, "create", "valid"

    if p.operation == "get":
        order_id = pick(pools.created[p.category], rnd) or pick(sum(pools.created.values(), []), rnd)
        if order_id:
            return "GET", f"/orders/{order_id}", {}, "get", "valid"
    elif p.operation == "cancel":
        order_id = pick(pools.cancelable[p.category], rnd, remove=True)
        if order_id is None:
            others = [c for c, ids in pools.cancelable.items() if ids]
            order_id = pick(pools.cancelable[rnd.choice(others)], rnd, remove=True) if others else None
        if order_id:
            return "POST", f"/cancel/{order_id}", {}, "cancel", "valid"
    return "POST", "/orders", {"json": payload_for(p)}, "create", "valid"


def register_created(pools: Pools, response: httpx.Response) -> None:
    try:
        order = response.json()
    except ValueError:
        return
    category = order.get("category")
    if category in pools.created:
        pools.created[category].append(order["order_id"])
        if category in pools.cancelable:
            pools.cancelable[category].append(order["order_id"])


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class CsvSink:
    def __init__(self, path: Path):
        self.path = path
        self._fh = path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=CSV_FIELDS)
        self._writer.writeheader()

    def write(self, row: dict) -> None:
        self._writer.writerow(row)
        self._fh.flush()  # si la corrida se corta, lo enviado ya quedó en disco

    def close(self) -> None:
        self._fh.close()


async def run(plan: list[Planned], base_url: str, time_scale: float, sink: CsvSink,
              seed: int, concurrency_cap: int) -> Counter:
    pools = Pools()
    rnd = random.Random(seed)
    loop = asyncio.get_running_loop()
    t0_loop = loop.time()
    t0_wall = datetime.now(timezone.utc)
    statuses: Counter = Counter()
    done = 0
    total = len(plan)
    print(f"Inicio de la corrida: {iso(t0_wall)} (UTC) · {total} solicitudes · time_scale={time_scale}")
    print(f"Fin estimado: {iso(t0_wall + timedelta(minutes=WINDOW_MIN / time_scale))}")

    # El semáforo evita que se formen colas dentro del pool de httpx (que se vuelve
    # muy costoso en CPU con miles de esperas). Si el servidor no da abasto, la
    # espera queda medida en send_lag_ms en vez de inflar la latencia del cliente.
    in_flight = asyncio.Semaphore(concurrency_cap)
    limits = httpx.Limits(max_connections=concurrency_cap, max_keepalive_connections=concurrency_cap)
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=httpx.Timeout(60.0),
                                 limits=limits) as client:

        async def fire(p: Planned) -> None:
            nonlocal done
            offset_s = p.scheduled_min * 60.0 / time_scale
            await asyncio.sleep(max(0.0, t0_loop + offset_s - loop.time()))

            async with in_flight:
                request_id = str(uuid.uuid4())
                method, path, kwargs, operation, event = resolve(p, pools, rnd)
                headers = {"X-Request-ID": request_id, **kwargs.pop("headers", {})}
                sent_wall = datetime.now(timezone.utc)
                lag_ms = (loop.time() - (t0_loop + offset_s)) * 1000
                started = time.perf_counter()
                status, error = "", ""
                try:
                    resp = await client.request(method, path, headers=headers, **kwargs)
                    status = resp.status_code
                    if operation == "create" and status == 201:
                        register_created(pools, resp)
                except httpx.HTTPError as exc:
                    error = type(exc).__name__
                latency_ms = (time.perf_counter() - started) * 1000

            sink.write({
                "request_id": request_id,
                "scheduled_min": f"{p.scheduled_min:.4f}",
                "scheduled_at": iso(t0_wall + timedelta(seconds=offset_s)),
                "sent_at": iso(sent_wall),
                "send_lag_ms": f"{lag_ms:.1f}",
                "operation": operation,
                "intended_event": event,
                "detail": p.detail if event == "invalid_payload" else ("scenario" if p.in_scenario else ""),
                "method": method,
                "path": path,
                "category": p.category,
                "customer_tier": p.customer_tier,
                "amount": p.amount,
                "expected_status": EXPECTED_STATUS.get((operation, event), ""),
                "status_code": status,
                "client_latency_ms": f"{latency_ms:.1f}",
                "error": error,
            })
            statuses[status or error] += 1
            done += 1
            if done % max(1, total // 10) == 0 or done == total:
                print(f"  {done}/{total} enviadas · {dict(sorted(statuses.items(), key=str))}", flush=True)

        await asyncio.gather(*(fire(p) for p in plan))
    return statuses


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def summarize(plan: list[Planned]) -> None:
    minutes = np.array([p.scheduled_min for p in plan])
    per_min = np.bincount(minutes.astype(int), minlength=61)
    events = Counter(p.intended_event for p in plan)
    ops = Counter(p.operation for p in plan if p.intended_event == "valid")
    in_sc = [p for p in plan if p.in_scenario]
    print(f"Plan: {len(plan)} solicitudes · μ={minutes.mean():.2f} min · σ={minutes.std(ddof=1):.2f} min"
          f" · pico={per_min.max()} req/min ({per_min.max() / 60:.1f} req/s) en el min {per_min.argmax()}")
    print(f"  eventos: {dict(events)}")
    print(f"  operaciones válidas: {dict(ops)}")
    if in_sc:
        bad = sum(p.intended_event != "valid" for p in in_sc)
        print(f"  escenario: {len(in_sc)} solicitudes afectadas, {bad} con error intencional ({bad / len(in_sc):.1%})")


def write_plan(plan: list[Planned], path: Path) -> None:
    sink = CsvSink(path)
    for p in plan:
        sink.write({
            "request_id": "", "scheduled_min": f"{p.scheduled_min:.4f}", "scheduled_at": "", "sent_at": "",
            "send_lag_ms": "", "operation": p.operation, "intended_event": p.intended_event,
            "detail": p.detail or ("scenario" if p.in_scenario else ""), "method": "", "path": "",
            "category": p.category, "customer_tier": p.customer_tier, "amount": p.amount,
            "expected_status": EXPECTED_STATUS.get((p.operation, p.intended_event), ""),
            "status_code": "", "client_latency_ms": "", "error": "",
        })
    sink.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=HERE / "config.json")
    ap.add_argument("--out", type=Path, default=None,
                    help="CSV de salida (default: requests.csv, o requests_plan.csv con --dry-run)")
    ap.add_argument("--url", default=None, help="sobrescribe target_url (p. ej. http://localhost:8080)")
    ap.add_argument("--time-scale", type=float, default=1.0,
                    help="factor de compresión del tiempo: 60 = la hora completa en 1 minuto")
    ap.add_argument("--dry-run", action="store_true", help="solo genera el plan, sin HTTP")
    ap.add_argument("--limit", type=int, default=None,
                    help="genera solo N solicitudes (misma distribución) para pruebas chicas")
    ap.add_argument("--max-connections", type=int, default=200)
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):  # consola de Windows (cp1252)
        stream.reconfigure(encoding="utf-8", errors="replace")

    if args.time_scale <= 0:
        ap.error("--time-scale debe ser > 0")
    cfg = load_config(args.config)
    n = min(cfg["n_requests"], args.limit) if args.limit else cfg["n_requests"]
    plan = build_plan(cfg, n)
    summarize(plan)

    if args.dry_run:
        out = args.out or HERE / "requests_plan.csv"
        write_plan(plan, out)
        print(f"Plan escrito en {out} (sin HTTP)")
        return

    url = args.url or cfg["target_url"]
    if "<" in url or not url.startswith(("http://", "https://")):
        sys.exit(f"target_url inválida: {url!r}. Copia la salida function_url de terraform en config.json o usa --url.")

    out = args.out or HERE / "requests.csv"
    sink = CsvSink(out)
    try:
        statuses = asyncio.run(run(plan, url, args.time_scale, sink, cfg["seed"], args.max_connections))
    except KeyboardInterrupt:
        print("\nInterrumpido; lo enviado hasta ahora quedó en el CSV.")
        statuses = None
    finally:
        sink.close()
    if statuses is not None:
        print(f"Listo: {out} · códigos: {dict(sorted(statuses.items(), key=str))}")


if __name__ == "__main__":
    main()
