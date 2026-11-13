"""Tools de consulta de produtos. Somente leitura, sem LLM.

Duas regras de desenho:
- o modelo não faz conta: promoção, PIX e parcelas já saem calculados daqui, e é isso que o
  output_guard confere depois;
- o modelo não escreve SQL: ele escolhe a tool e os argumentos, que são validados em Python
  antes de chegar ao repositório (`db.py`). Argumento inválido vira `{"error": ...}`, com a
  lista de opções válidas, para o modelo se corrigir na iteração seguinte.
"""

import json
from contextlib import closing

from agent import db

MAX_RESULTS = 10
MAX_QUERY_CHARS = 200
MAX_ALTERNATIVES = 3
PIX_DISCOUNT = 0.05

# Regra 3.1 do manual: parcela mínima por faixa de número de parcelas (sem juros, até 12x).
# Até 3x vale o piso de R$ 50 por parcela; de 4x a 6x, R$ 80; de 7x a 12x, R$ 100.
MAX_INSTALLMENTS = 12
MIN_INSTALLMENT_BRL = {**dict.fromkeys(range(2, 4), 50.0), **dict.fromkeys(range(4, 7), 80.0),
                       **dict.fromkeys(range(7, 13), 100.0)}


class ToolError(ValueError):
    """Argumento inválido; a mensagem vai para o modelo."""


def _money(value: float) -> float:
    return round(value + 1e-9, 2)


def _installments(price: float) -> dict:
    """Maior número de parcelas sem juros que respeita a parcela mínima da faixa."""
    for count in range(MAX_INSTALLMENTS, 1, -1):
        if price / count >= MIN_INSTALLMENT_BRL[count]:
            return {"count": count, "value_brl": _money(price / count)}
    return {"count": 1, "value_brl": _money(price)}


def _availability(row: dict) -> str:
    if row["status"] == "active":
        return "available" if row["stock_quantity"] > 0 else "out_of_stock"
    return row["status"]  # discontinued, coming_soon


def _item(row: dict) -> dict:
    price = row["price_brl"]
    discount = row["discount_percent"]
    promo_price = _money(price * (1 - discount / 100)) if discount else None
    return {
        "product_id": row["product_id"],
        "name": row["name"],
        "category": row["category"],
        "price_brl": price,
        "stock_quantity": row["stock_quantity"],
        "availability": _availability(row),
        "promotion": (
            {"discount_percent": discount, "description": row["promotion_description"]} if discount else None
        ),
        "promo_price_brl": promo_price,
        "pix_price_brl": None if discount else _money(price * (1 - PIX_DISCOUNT)),  # PIX não acumula
        "installments": _installments(promo_price or price),
    }


# ---------- validação ----------


def _price(name: str, value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ToolError(f"{name} precisa ser um número maior ou igual a zero.")
    return value


def _category(conn, name) -> tuple[int | None, str | None]:
    if name is None:
        return None, None
    categories = db.get_categories(conn)
    if isinstance(name, str):
        for c in categories:
            if db.normalize(c["name"]) == db.normalize(name.strip()):
                return c["category_id"], c["name"]
    valid = ", ".join(c["name"] for c in categories)
    raise ToolError(f"Categoria desconhecida. Categorias válidas: {valid}.")


def _specs(conn, specs, category_id) -> dict[str, str] | None:
    if specs is None:
        return None
    if not isinstance(specs, dict):
        raise ToolError('specs precisa ser um objeto {chave: valor}, como {"strings": "nylon"}.')
    options = db.spec_options(conn, category_id)
    normalized = {}
    for key, value in specs.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ToolError("Em specs, chave e valor precisam ser texto (números também, entre aspas).")
        k, v = db.normalize(key.strip()), db.normalize(value.strip())
        if k not in options:
            raise ToolError(f"Spec '{key}' desconhecida. Chaves válidas: {', '.join(sorted(options))}.")
        if v not in options[k]:
            raise ToolError(f"Valor '{value}' desconhecido para '{key}'. Valores válidos: {', '.join(sorted(options[k]))}.")
        normalized[k] = v
    return normalized


# ---------- tools ----------


def search_products(query=None, category=None, specs=None, min_price=None, max_price=None, only_available=True) -> dict:
    try:
        if query is not None and (not isinstance(query, str) or len(query) > MAX_QUERY_CHARS):
            raise ToolError(f"query precisa ser texto de até {MAX_QUERY_CHARS} caracteres.")
        if not isinstance(only_available, bool):
            raise ToolError("only_available precisa ser verdadeiro ou falso.")
        min_price, max_price = _price("min_price", min_price), _price("max_price", max_price)
        with closing(db.connect_ro()) as conn:
            category_id, category_name = _category(conn, category)
            normalized_specs = _specs(conn, specs, category_id)
            filters = dict(
                query=db.normalize(query) if query else None, category_id=category_id,
                min_price=min_price, max_price=max_price, only_available=only_available,
            )
            rows = db.find_products(conn, specs=normalized_specs, limit=MAX_RESULTS, **filters)
            result = {
                "products": [_item(r) for r in rows],
                "count": db.count_products(conn, specs=normalized_specs, **filters),
                "filters": {k: v for k, v in {
                    "query": query or None, "category": category_name, "specs": specs,
                    "min_price": min_price, "max_price": max_price,
                }.items() if v is not None} | {"only_available": only_available},
            }
            if normalized_specs:
                result["count_without_specs"] = db.count_products(conn, **filters)
            return result
    except ToolError as exc:
        return {"error": str(exc)}


def get_product_details(product_id) -> dict:
    if isinstance(product_id, bool) or not isinstance(product_id, int) or product_id < 1:
        return {"error": "product_id precisa ser um número inteiro positivo."}
    with closing(db.connect_ro()) as conn:
        row = db.get_product(conn, product_id)
        if row is None:
            return {"error": f"Produto {product_id} não encontrado."}
        item = _item(row)
        alternatives = []
        if item["availability"] != "available":
            alternatives = [_item(r) for r in db.find_alternatives(conn, row, MAX_ALTERNATIVES)]
    return item | {
        "description": row["description"],
        "specs": json.loads(row["specs"]) if row["specs"] else {},
        "alternatives": alternatives,
    }


def list_categories() -> dict:
    with closing(db.connect_ro()) as conn:
        categories = db.get_categories(conn)
    return {"categories": [{"name": c["name"], "product_count": c["product_count"]} for c in categories]}
