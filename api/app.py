import csv
import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Inventory API")

PRODUCTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "products.csv")
FIELD_NAMES = ["id", "name", "quantity", "unit"]


class CreateProductRequest(BaseModel):
    name: str
    quantity: int
    unit: str


class UpdateStockRequest(BaseModel):
    delta: int


def _read_products():
    if not os.path.exists(PRODUCTS_FILE):
        return []
    with open(PRODUCTS_FILE, newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _write_products(products):
    with open(PRODUCTS_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELD_NAMES)
        writer.writeheader()
        writer.writerows(products)


def _next_id(products):
    if not products:
        return 1
    return max(int(p["id"]) for p in products) + 1


@app.get("/inventory")
def get_inventory():
    products = _read_products()
    for p in products:
        p["quantity"] = int(p["quantity"])
    return products


@app.post("/inventory", status_code=201)
def create_product(req: CreateProductRequest):
    products = _read_products()
    new_id = _next_id(products)
    new_product = {"id": str(new_id), "name": req.name, "quantity": str(req.quantity), "unit": req.unit}
    products.append(new_product)
    _write_products(products)
    new_product["quantity"] = int(new_product["quantity"])
    return new_product


@app.patch("/inventory/{product_id}")
def update_stock(product_id: int, req: UpdateStockRequest):
    products = _read_products()
    for p in products:
        if int(p["id"]) == product_id:
            new_qty = int(p["quantity"]) + req.delta
            if new_qty < 0:
                raise HTTPException(status_code=400, detail="Stock cannot go below zero")
            p["quantity"] = str(new_qty)
            _write_products(products)
            p["quantity"] = int(p["quantity"])
            return p
    raise HTTPException(status_code=404, detail="Product not found")


@app.get("/inventory/alerts")
def get_alerts(threshold: Optional[int] = 10):
    products = _read_products()
    alerts = [p for p in products if int(p["quantity"]) < threshold]
    for p in alerts:
        p["quantity"] = int(p["quantity"])
    return alerts
