"""Sanidade dos cenários e2e e do parser de R$. Sem API, roda no pytest padrão."""

import csv
from pathlib import Path

from tests.e2e.helpers import brl_values, digits, norm
from tests.e2e.scenarios import ANA, EXTRA_ORDER_ITEMS, EXTRA_ORDERS, GUSTAVO, LUCAS, PEDRO, SCENARIOS, VISITOR

DATA = Path(__file__).resolve().parent.parent / "data"


def rows(name):
    with open(DATA / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_scenario_ids_unique_and_examples_cover_1_to_5():
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids))
    assert {s.example for s in SCENARIOS if s.example} == {1, 2, 3, 4, 5}


def test_phones_match_the_intended_customers():
    by_phone = {digits(r["phone"]): r["name"] for r in rows("customers.csv")}
    assert by_phone[digits(ANA)].startswith("Ana Carolina")
    assert by_phone[digits(PEDRO)].startswith("Pedro Henrique")
    assert by_phone[digits(LUCAS)].startswith("Lucas Mendes")
    assert by_phone[digits(GUSTAVO)].startswith("Gustavo Teixeira")
    assert digits(VISITOR) not in by_phone


def test_extra_orders_do_not_collide_with_real_ones():
    real = {r["order_id"] for r in rows("orders.csv")}
    extra = {line.split(",")[0] for line in EXTRA_ORDERS}
    assert not real & extra
    assert extra == {line.split(",")[0] for line in EXTRA_ORDER_ITEMS}


def test_expected_prices_match_the_catalog():
    products = {r["product_id"]: float(r["price_brl"]) for r in rows("products.csv")}
    promos = {r["product_id"]: float(r["discount_percent"]) for r in rows("promotions.csv") if r["is_active"] == "1"}
    assert products["95"] == 2199 and "95" not in promos
    assert round(products["95"] * 0.95, 2) == 2089.05  # PIX 5%
    assert round(products["94"] * (1 - promos["94"] / 100), 2) == 5519.08  # promoção ativa de 8%
    assert round(products["94"] * 0.95, 2) == 5699.05  # PIX sobre promoção: não pode aparecer


def test_visitor_flow_uses_the_real_owner_of_order_14():
    customers = {r["customer_id"]: r for r in rows("customers.csv")}
    owner = customers[{r["order_id"]: r for r in rows("orders.csv")}["14"]["customer_id"]]
    assert owner["email"] == "diego.castro@coldmail.com"
    assert any(c["email"] == "diego.castro@jmail.com" for c in customers.values())  # o homônimo existe


def test_brl_parser_and_norm():
    assert brl_values("de R$ 2.199,00 por R$2.089,05 ou R$ 599,9 e R$1000") == [2199.0, 2089.05, 599.9, 1000.0]
    assert norm("Não Consegui") == "nao consegui"
