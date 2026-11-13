"""Tools de consulta de produtos. Somente leitura, sem LLM.

Duas regras de desenho:
- o modelo não faz conta: promoção, PIX e parcelas já saem calculados daqui, e é isso que o
  output_guard confere depois;
- o modelo não escreve SQL: ele escolhe a tool e os argumentos, que são validados em Python
  antes de chegar ao repositório (`db.py`). Argumento inválido vira `{"error": ...}`, com a
  lista de opções válidas, para o modelo se corrigir na iteração seguinte.
"""

import json
import os
import re
from contextlib import closing
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from agent import db

MAX_RESULTS = 10
MAX_QUERY_CHARS = 200
MAX_ALTERNATIVES = 3
PIX_DISCOUNT = 0.05
MAX_INSTALLMENTS = 12

TIMEZONE = ZoneInfo("America/Campo_Grande")
RECENT_DELIVERY_DAYS = 30  # janela de troca por defeito
MAX_ORDER_SUMMARIES = 5
# Prazo de entrega da política (seção 5), em dias úteis, para pedido confirmado sem previsão.
# Outras cidades: o maior prazo entre PAC, SEDEX e Jadlog, porque a base não registra a modalidade.
POLICY_DELIVERY_DAYS = {"metropolitana": 3, "outras_cidades": 12}
NOT_FOUND = "Pedido não encontrado."

# Regra 3.1 do manual: compra abaixo de R$ 50 não parcela; até 3x não há parcela mínima;
# de 4x a 6x, R$ 80; de 7x a 12x, R$ 100.
MIN_PURCHASE_TO_INSTALL_BRL = 50.0
MIN_INSTALLMENT_BRL = {**dict.fromkeys(range(2, 4), 0.0), **dict.fromkeys(range(4, 7), 80.0),
                       **dict.fromkeys(range(7, 13), 100.0)}


class ToolError(ValueError):
    """Argumento inválido; a mensagem vai para o modelo."""


def _money(value: float) -> float:
    return round(value + 1e-9, 2)


def _installments(price: float) -> dict:
    """Maior número de parcelas sem juros que respeita a parcela mínima da faixa."""
    if price < MIN_PURCHASE_TO_INSTALL_BRL:
        return {"count": 1, "value_brl": _money(price)}
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


# ---------- data ----------


def today() -> datetime:
    """A única fonte de data do código: REFERENCE_DATE (ou a data real, se vazia) + o horário real.

    Os dados da loja terminam em março de 2026; a data simulada faz prazos e atrasos fazerem sentido.
    """
    now = datetime.now(TIMEZONE)
    reference = os.environ.get("REFERENCE_DATE", "").strip()
    if not reference:
        return now
    return datetime.combine(date.fromisoformat(reference), now.timetz())


def add_business_days(start: date, days: int) -> date:
    """Soma dias úteis (segunda a sexta). Feriados são ignorados."""
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


# ---------- cliente e pedidos ----------


def _digits(text) -> str:
    return re.sub(r"\D", "", text) if isinstance(text, str) else ""


def identify_customer(phone) -> dict | None:
    """Cliente do telefone do canal (só os dígitos contam), ou None para visitante."""
    digits = _digits(phone)
    if not digits:
        return None
    with closing(db.connect_ro()) as conn:
        row = db.find_customer_by_phone(conn, digits)
    return {"customer_id": row["customer_id"], "first_name": row["name"].split()[0]} if row else None


def _metro_cities() -> set[str]:
    raw = os.environ.get("METRO_CITIES") or "Campo Grande"
    return {db.normalize(c.strip()) for c in raw.split(",") if c.strip()}


def _delivery(order: dict, now: date) -> dict:
    """Região, prazo esperado e atraso, calculados aqui para o modelo não fazer conta de data."""
    region = "metropolitana" if db.normalize(order["city"]) in _metro_cities() else "outras_cidades"
    expected_by = source = None
    if order["status"] in ("confirmed", "shipped"):
        if order["estimated_delivery"]:  # a previsão do pedido prevalece sobre a política
            expected_by, source = date.fromisoformat(order["estimated_delivery"]), "pedido"
        else:
            start = date.fromisoformat(order["order_date"])
            expected_by, source = add_business_days(start, POLICY_DELIVERY_DAYS[region]), "politica"
    is_late = expected_by is not None and now > expected_by
    return {
        "delivery_region": region,
        "expected_by": expected_by.isoformat() if expected_by else None,
        "deadline_source": source,
        "awaiting_payment": order["status"] == "pending",
        "is_late": is_late,
        "days_late": (now - expected_by).days if is_late else 0,
    }


def _order_detail(conn, order: dict, now: date) -> dict:
    since = None
    if order["status"] == "delivered" and order["estimated_delivery"]:  # a previsão faz de data de recebimento
        since = (now - date.fromisoformat(order["estimated_delivery"])).days
    return {
        "order_id": order["order_id"],
        "order_date": order["order_date"],
        "status": order["status"],
        "total_brl": order["total_brl"],
        "payment_method": order["payment_method"],
        "tracking_code": order["tracking_code"],
        "estimated_delivery": order["estimated_delivery"],
        "notes": order["notes"],
        "items": db.get_order_items(conn, order["order_id"]),
        "days_since_delivery": since,
    } | _delivery(order, now)


def _order_summary(conn, order: dict) -> dict:
    return {
        "order_id": order["order_id"],
        "order_date": order["order_date"],
        "status": order["status"],
        "products": [i["name"] for i in db.get_order_items(conn, order["order_id"])],
    }


def _owns(conn, order_id: int, contact) -> bool:
    """O e-mail ou o telefone informado pelo visitante bate com o dono do pedido?"""
    if not isinstance(contact, str) or not contact.strip():
        return False
    owner = db.get_order_owner_contact(conn, order_id)
    if owner is None:
        return False
    return contact.strip().lower() == owner["email"].lower() or (
        bool(_digits(contact)) and _digits(contact) == _digits(owner["phone"])
    )


def get_my_orders(order_id=None, email_or_phone=None, *, customer_id=None) -> dict:
    """Pedidos do cliente. `customer_id` vem do código (telefone do canal), nunca do modelo.

    Pedido de outro cliente e pedido inexistente têm a mesma resposta, para não revelar que existe.
    """
    if order_id is not None and (isinstance(order_id, bool) or not isinstance(order_id, int) or order_id < 1):
        return {"error": "order_id precisa ser um número inteiro positivo."}
    now = today().date()
    with closing(db.connect_ro()) as conn:
        if customer_id is None:  # visitante: pedido + contato do dono
            if order_id is None or not isinstance(email_or_phone, str) or not email_or_phone.strip():
                return {"error": "Para consultar um pedido, informe o número do pedido e o e-mail ou telefone do cadastro."}
            if not _owns(conn, order_id, email_or_phone):
                return {"error": NOT_FOUND}
            # só o pedido verificado: sem total nem lista, para não revelar quantos pedidos o dono tem
            return {"order": _order_detail(conn, db.get_order(conn, order_id), now)}
        if order_id is not None:
            order = db.get_order(conn, order_id, customer_id)
            if order is None:
                return {"error": NOT_FOUND}
            return {"total_orders": db.count_orders(conn, customer_id), "order": _order_detail(conn, order, now),
                    "other_orders": []}
        cutoff = (now - timedelta(days=RECENT_DELIVERY_DAYS)).isoformat()
        ranked = db.ranked_orders(conn, customer_id, cutoff, limit=1 + MAX_ORDER_SUMMARIES)
        return {
            "total_orders": db.count_orders(conn, customer_id),
            "order": _order_detail(conn, ranked[0], now) if ranked else None,
            "other_orders": [_order_summary(conn, o) for o in ranked[1:]],
        }
