"""API de pedidos (orders) para Cloud Run functions.

Rutas:
    POST /orders         crea un pedido                      -> 201
    GET  /orders/{id}    consulta un pedido                  -> 200
    POST /cancel/{id}    cancela un pedido                   -> 200

Errores de cliente: 400 payload inválido, 404 recurso inexistente,
409 cambio de estado imposible. Fallas propias: FAILURE_RATE (prob. de 500)
y EXTRA_LATENCY_MS (latencia adicional).

Cada solicitud termina con UNA línea JSON en stdout (logging estructurado).

Sobre el estado: con concurrency=1 y autoscaling hay varias instancias y la
memoria no se comparte. Por eso el order_id es autocontenido
(tier-categoría-centavos-nonce-checksum): cualquier instancia puede resolverlo.
Los pedidos "digital" se entregan al crearse, así que cancelarlos da 409 en
cualquier instancia; cancelar dos veces da 409 solo dentro de la misma instancia.
"""

import hashlib
import json
import os
import random
import re
import secrets
import sys
import threading
import time
import uuid

import functions_framework

TIERS = ("free", "standard", "pro")
CATEGORIES = ("electronics", "books", "clothing", "home", "digital")
INSTANT_FULFILLMENT = {"digital"}
MAX_AMOUNT = 10_000

_ID_RE = re.compile(r"^ord-([a-z]+)-([a-z]+)-(\d{1,9})-([0-9a-f]{8})-([0-9a-f]{6})$")
_CHECKSUM_SALT = "cc3106-orders"

_cancelled: set[str] = set()
_lock = threading.Lock()
_stdout_lock = threading.Lock()


class ApiError(Exception):
    def __init__(self, status: int, error_type: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.error_type = error_type
        self.detail = detail


# --------------------------------------------------------------------------
# Order IDs
# --------------------------------------------------------------------------

def _checksum(tier: str, category: str, cents: int, nonce: str) -> str:
    raw = f"{tier}|{category}|{cents}|{nonce}|{_CHECKSUM_SALT}".encode()
    return hashlib.sha256(raw).hexdigest()[:6]


def make_order_id(tier: str, category: str, amount: float) -> str:
    cents = int(round(amount * 100))
    nonce = secrets.token_hex(4)
    return f"ord-{tier}-{category}-{cents}-{nonce}-{_checksum(tier, category, cents, nonce)}"


def parse_order_id(order_id: str) -> dict | None:
    m = _ID_RE.match(order_id)
    if not m:
        return None
    tier, category, cents, nonce, chk = m.groups()
    if tier not in TIERS or category not in CATEGORIES:
        return None
    if chk != _checksum(tier, category, int(cents), nonce):
        return None
    return {"order_id": order_id, "customer_tier": tier, "category": category,
            "amount": int(cents) / 100}


def _order_status(order: dict) -> str:
    if order["category"] in INSTANT_FULFILLMENT:
        return "fulfilled"
    with _lock:
        return "cancelled" if order["order_id"] in _cancelled else "created"


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------

def _maybe_fail() -> None:
    """Falla interna simulada; se aplica después de validar y antes de mutar estado."""
    rate = float(os.environ.get("FAILURE_RATE", "0") or 0)
    if rate > 0 and random.random() < rate:
        raise ApiError(500, "simulated_failure", "simulated internal failure")


def create_order(request, ctx: dict) -> tuple[int, dict]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_json", "body must be a JSON object")

    # Atributos de negocio para el log aunque el payload resulte inválido.
    if isinstance(body.get("customer_tier"), str):
        ctx["customer_tier"] = body["customer_tier"]
    if isinstance(body.get("category"), str):
        ctx["category"] = body["category"]
    if isinstance(body.get("amount"), (int, float)) and not isinstance(body["amount"], bool):
        ctx["amount"] = body["amount"]

    customer_id = body.get("customer_id")
    if not isinstance(customer_id, str) or not customer_id.strip():
        raise ApiError(400, "missing_field", "customer_id is required")
    if body.get("customer_tier") not in TIERS:
        raise ApiError(400, "invalid_field", f"customer_tier must be one of {TIERS}")
    if body.get("category") not in CATEGORIES:
        raise ApiError(400, "invalid_field", f"category must be one of {CATEGORIES}")
    amount = body.get("amount")
    if (not isinstance(amount, (int, float)) or isinstance(amount, bool)
            or not 0 < amount <= MAX_AMOUNT):
        raise ApiError(400, "invalid_amount", f"amount must be in (0, {MAX_AMOUNT}]")

    _maybe_fail()

    order_id = make_order_id(body["customer_tier"], body["category"], amount)
    order = parse_order_id(order_id)
    ctx["order_id"] = order_id
    return 201, {**order, "customer_id": customer_id, "status": _order_status(order)}


def _load_order(order_id: str, ctx: dict) -> dict:
    ctx["order_id"] = order_id
    order = parse_order_id(order_id)
    if order is None:
        raise ApiError(404, "order_not_found", f"order {order_id!r} does not exist")
    ctx.update(customer_tier=order["customer_tier"], category=order["category"],
               amount=order["amount"])
    return order


def get_order(order_id: str, ctx: dict) -> tuple[int, dict]:
    order = _load_order(order_id, ctx)
    _maybe_fail()
    return 200, {**order, "status": _order_status(order)}


def cancel_order(order_id: str, ctx: dict) -> tuple[int, dict]:
    order = _load_order(order_id, ctx)
    if order["category"] in INSTANT_FULFILLMENT:
        raise ApiError(409, "order_fulfilled", "digital orders are fulfilled on creation")
    with _lock:
        if order_id in _cancelled:
            raise ApiError(409, "already_cancelled", "order is already cancelled")
    _maybe_fail()
    with _lock:
        _cancelled.add(order_id)
    return 200, {**order, "status": "cancelled"}


def route(request, ctx: dict) -> tuple[int, dict]:
    method = request.method.upper()
    parts = [p for p in request.path.split("/") if p]

    if parts == ["orders"]:
        ctx["endpoint"] = "POST /orders"
        if method != "POST":
            raise ApiError(405, "method_not_allowed", "use POST /orders")
        return create_order(request, ctx)

    if len(parts) == 2 and parts[0] == "orders":
        ctx["endpoint"] = "GET /orders/{id}"
        if method != "GET":
            raise ApiError(405, "method_not_allowed", "use GET /orders/{id}")
        return get_order(parts[1], ctx)

    if len(parts) == 2 and parts[0] == "cancel":
        ctx["endpoint"] = "POST /cancel/{id}"
        if method != "POST":
            raise ApiError(405, "method_not_allowed", "use POST /cancel/{id}")
        return cancel_order(parts[1], ctx)

    ctx["endpoint"] = "unknown"
    raise ApiError(404, "route_not_found", f"no route for {method} {request.path}")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def _outcome(status: int) -> str:
    if status >= 500:
        return "server_error"
    if status >= 400:
        return "client_error"
    return "success"


_SEVERITY = {"success": "INFO", "client_error": "WARNING", "server_error": "ERROR"}


def log_request(ctx: dict, status: int, error_type: str | None, latency_ms: float) -> None:
    outcome = _outcome(status)
    entry = {
        "severity": _SEVERITY[outcome],
        "message": "request_completed",
        "request_id": ctx["request_id"],
        "endpoint": ctx.get("endpoint", "unknown"),
        "method": ctx["method"],
        "path": ctx["path"],
        "status_code": status,
        "outcome": outcome,
        "error_type": error_type,
        "latency_ms": round(latency_ms, 1),
        "customer_tier": ctx.get("customer_tier"),
        "category": ctx.get("category"),
        "amount": ctx.get("amount"),
        "order_id": ctx.get("order_id"),
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _stdout_lock:  # una sola escritura por línea: no se intercalan entre hilos
        sys.stdout.write(line)
        sys.stdout.flush()


@functions_framework.http
def handle(request):
    started = time.perf_counter()
    request_id = request.headers.get("X-Request-ID") or f"missing-{uuid.uuid4()}"
    ctx = {"request_id": request_id, "method": request.method, "path": request.path}
    error_type = None

    try:
        extra_ms = float(os.environ.get("EXTRA_LATENCY_MS", "0") or 0)
        if extra_ms > 0:
            time.sleep(extra_ms / 1000)
        status, body = route(request, ctx)
    except ApiError as err:
        status, error_type = err.status, err.error_type
        body = {"error": err.error_type, "detail": err.detail}
    except Exception as err:  # noqa: BLE001 - cualquier bug debe quedar como 500 en el log
        status, error_type = 500, "unhandled_exception"
        body = {"error": error_type, "detail": type(err).__name__}

    log_request(ctx, status, error_type, (time.perf_counter() - started) * 1000)
    headers = {"Content-Type": "application/json", "X-Request-ID": request_id}
    return json.dumps(body), status, headers
