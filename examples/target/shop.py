"""A tiny "shop" microservice used as the default FaultLine demo target.

It is deliberately small but has a real hot path: POST /api/orders runs an
inventory check that does bounded CPU work (SHOP_WORKLOAD iterations), so
cpu_pressure and network_delay faults produce measurable SLO breaches instead of
noise. Binds to 127.0.0.1 only.

Run directly:  python -m examples.target.shop --port 8091
"""

from __future__ import annotations

import argparse
import os
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="shop (faultline demo target)", version="1.0.0")

PRODUCTS: dict[str, dict] = {
    "sku-001": {"id": "sku-001", "name": "Mechanical Keyboard", "price_cents": 8900},
    "sku-002": {"id": "sku-002", "name": "USB-C Dock", "price_cents": 12450},
    "sku-003": {"id": "sku-003", "name": "Monitor Arm", "price_cents": 6700},
    "sku-004": {"id": "sku-004", "name": "Webcam", "price_cents": 5400},
    "sku-005": {"id": "sku-005", "name": "Desk Mat", "price_cents": 2900},
}

ORDERS: dict[str, dict] = {}


class OrderRequest(BaseModel):
    product_id: str
    quantity: int = 1


def _inventory_check(workload: int) -> int:
    """Bounded CPU work standing in for a real inventory/pricing pipeline."""
    total = 0
    for i in range(workload):
        total += (i * i) % 97
    return total


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "ts": time.time()}


@app.get("/api/products")
def list_products() -> list[dict]:
    return list(PRODUCTS.values())


@app.post("/api/orders", status_code=201)
def create_order(req: OrderRequest) -> dict:
    product = PRODUCTS.get(req.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="unknown product")
    if not 1 <= req.quantity <= 100:
        raise HTTPException(status_code=422, detail="quantity out of range")
    workload = int(os.environ.get("SHOP_WORKLOAD", "250000"))
    _inventory_check(workload)
    order = {
        "id": uuid.uuid4().hex[:12],
        "product_id": product["id"],
        "quantity": req.quantity,
        "total_cents": product["price_cents"] * req.quantity,
        "created_at": time.time(),
    }
    ORDERS[order["id"]] = order
    return order


@app.get("/api/orders/{order_id}")
def get_order(order_id: str) -> dict:
    order = ORDERS.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="unknown order")
    return order


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()

    import uvicorn

    # Local-only by design; the demo target is never meant to be exposed.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
