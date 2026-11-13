"""Identificação do cliente, consulta de pedidos e isolamento entre clientes. Sem LLM.

Interface esperada (commit 10). Em todas as tools, erro de validação ou de acesso vira
`{"error": "..."}`, nunca uma exceção:

    tools.today() -> datetime               # REFERENCE_DATE (ou a data real, se vazia) + horário real
                                            # de America/Campo_Grande; única fonte de data do código
    tools.add_business_days(start: date, days: int) -> date   # pula sábado e domingo; ignora feriados

    tools.identify_customer(phone) -> {"customer_id": int, "first_name": str} | None
        # compara só os dígitos do telefone; número desconhecido -> None (visitante); nunca devolve
        # e-mail, telefone ou cidade

    tools.get_my_orders(order_id=None, email_or_phone=None, *, customer_id=None) -> {
        "total_orders": int,
        "order": detail | None,             # o 1º do ranking (ou o pedido pedido por `order_id`)
        "other_orders": [summary, ...],     # até 5, na ordem do ranking
    }
    # `customer_id` é injetado pelo código (resolvido pelo telefone do canal); não é argumento do
    # modelo. Sem ele, a pessoa é visitante: `order_id` + `email_or_phone` são obrigatórios e
    # precisam bater com o dono do pedido; o retorno é só {"order": detail}, sem total nem lista. Com ele, só os pedidos do próprio cliente são visíveis,
    # e `email_or_phone` é ignorado.

    detail = {
        "order_id", "order_date", "status", "total_brl", "payment_method", "tracking_code",
        "estimated_delivery", "notes",
        "items": [{"product_id", "name", "quantity"}, ...],
        "days_since_delivery": int | None,  # só pedido entregue (estimated_delivery como proxy)
        "delivery_region": "metropolitana" | "outras_cidades",   # METRO_CITIES (default: Campo Grande)
        "expected_by": "YYYY-MM-DD" | None, "deadline_source": "pedido" | "politica" | None,
        "awaiting_payment": bool,           # pedido pendente: o relógio de entrega ainda não começou
        "is_late": bool, "days_late": int,
    }
    summary = {"order_id", "order_date", "status", "products": [nome, ...]}

Ranking (feito no SQL): em aberto (pending, confirmed, shipped) > entregue há até 30 dias > o resto;
dentro de cada grupo, do mais recente para o mais antigo (`order_date`).
"""

import json
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent import db, ingest, tools

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"

# Cliente (id) -> telefone, como em customers.csv
ANA = 2  # (67) 99654-7821, Campo Grande; pedido 8 (enviado, atrasado)
PEDRO = 3  # recebe os pedidos sintéticos do ranking
LUCAS = 1  # pedido 4 entregue há muito tempo + 1 entregue recente (sintético)
BRUNO_11 = 11  # Três Lagoas, bruno.martins@jmail.com, pedido 10
BRUNO_43 = 43  # Três Lagoas, MESMO e-mail do 11, telefone diferente
DIEGO_13 = 13  # pedido 14
DIEGO_47 = 47  # nome parecido, outro e-mail e telefone

# Pedidos sintéticos, só na cópia temporária dos CSVs (data/ nunca é alterado).
# orders.csv: order_id,customer_id,order_date,status,total_brl,payment_method,tracking_code,estimated_delivery,notes
SYNTHETIC_ORDERS = [
    # Pedro (3), com o 1 (entregue, antigo) e o 19 (cancelado) da base: 8 pedidos no total.
    "201,3,2026-03-20,pending,100,pix,,,",
    "202,3,2026-03-18,shipped,100,pix,BRZZ0000202BR,2026-03-30,",
    "203,3,2026-03-24,confirmed,100,pix,,,",
    "204,3,2026-03-10,delivered,100,pix,BRZZ0000204BR,2026-03-20,",  # entregue há 5 dias
    "205,3,2026-02-01,delivered,100,pix,BRZZ0000205BR,2026-02-10,",  # entregue há 43 dias
    "206,3,2026-03-01,delivered,100,pix,BRZZ0000206BR,2026-03-05,",  # entregue há 20 dias
    # Amanda (20): previsão de entrega é hoje; ainda não está atrasado.
    "207,20,2026-03-20,shipped,100,pix,BRZZ0000207BR,2026-03-25,",
    # Bruno Carvalho (27), Dourados: confirmado, sem previsão.
    "208,27,2026-03-02,confirmed,100,pix,,,",
    # Lucas (1): entregue recente, e o pedido 4 da base é antigo.
    "209,1,2026-03-15,delivered,100,pix,BRZZ0000209BR,2026-03-23,",
]
# order_items.csv: order_id,quantity,product_id
SYNTHETIC_ITEMS = [f"{n},1,95" for n in (201, 202, 204, 205, 206, 207, 208, 209)] + ["203,1,95", "203,2,82"]


def append_rows(path, rows):
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + "\n".join(rows) + "\n", encoding="utf-8")


@pytest.fixture
def ready(store):
    ingest.ingest_all()
    return store


@pytest.fixture
def synthetic(store):
    append_rows(store.data_dir / "orders.csv", SYNTHETIC_ORDERS)
    append_rows(store.data_dir / "order_items.csv", SYNTHETIC_ITEMS)
    ingest.ingest_all()
    return store


def detail(customer_id, order_id):
    result = tools.get_my_orders(order_id=order_id, customer_id=customer_id)
    assert "error" not in result, result
    return result["order"]


def ranking(customer_id):
    result = tools.get_my_orders(customer_id=customer_id)
    assert "error" not in result, result
    return [result["order"]["order_id"]] + [o["order_id"] for o in result["other_orders"]]


def all_text(value) -> str:
    return json.dumps(value, ensure_ascii=False).lower()


# ---------- today(): a única fonte de data ----------


def test_today_uses_reference_date_with_campo_grande_clock(ready):
    now = tools.today()
    assert now.date() == date(2026, 3, 25)
    assert str(now.tzinfo) == "America/Campo_Grande"


def test_today_falls_back_to_the_real_date_when_reference_date_is_empty(ready, monkeypatch):
    monkeypatch.setenv("REFERENCE_DATE", "")
    assert tools.today().date() == datetime.now(ZoneInfo("America/Campo_Grande")).date()


def test_orders_follow_today(ready, monkeypatch):
    """Os prazos saem de `today()`: mudar a data de referência muda o atraso."""
    assert detail(ANA, 8)["days_late"] == 25
    monkeypatch.setenv("REFERENCE_DATE", "2026-03-01")  # 1 dia depois da previsão (28/02)
    assert detail(ANA, 8)["days_late"] == 1


def test_no_code_calls_date_today_directly():
    pattern = re.compile(r"\b(date|datetime)\.today\(")
    offenders = [p.name for p in AGENT_DIR.glob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


# ---------- dias úteis ----------


@pytest.mark.parametrize(
    "start, days, expected",
    [
        (date(2026, 2, 20), 3, date(2026, 2, 25)),  # sexta + 3 = quarta
        (date(2026, 3, 5), 3, date(2026, 3, 10)),  # quinta + 3 = terça
        (date(2026, 3, 9), 5, date(2026, 3, 16)),  # segunda + 5 = segunda seguinte
        (date(2026, 2, 21), 1, date(2026, 2, 23)),  # sábado + 1 = segunda
        (date(2026, 2, 22), 1, date(2026, 2, 23)),  # domingo + 1 = segunda
        (date(2026, 2, 25), 12, date(2026, 3, 13)),
        (date(2026, 3, 9), 0, date(2026, 3, 9)),
    ],
)
def test_add_business_days_skips_weekends(start, days, expected):
    assert tools.add_business_days(start, days) == expected


# ---------- identificação pelo telefone do canal ----------


def test_identify_customer_ignores_phone_formatting(ready):
    for phone in ("(67) 99654-7821", "67996547821", "67 99654 7821", " (67)99654-7821 "):
        assert tools.identify_customer(phone) == {"customer_id": ANA, "first_name": "Ana"}


@pytest.mark.parametrize("phone", ["67900000000", "(67) 99654-7822", "", None, "sem numero", "7821"])
def test_unknown_number_is_a_visitor(ready, phone):
    assert tools.identify_customer(phone) is None


def test_similar_registrations_stay_separate(ready):
    """Bruno 11 e Bruno 43 compartilham o e-mail, não o telefone; Diego 13 e 47 são nomes parecidos."""
    assert tools.identify_customer("(67) 98543-2109")["customer_id"] == BRUNO_11
    assert tools.identify_customer("(67) 99456-3456")["customer_id"] == BRUNO_43
    assert tools.identify_customer("(67) 98210-9876")["customer_id"] == DIEGO_13
    assert tools.identify_customer("(67) 99890-7890")["customer_id"] == DIEGO_47


def test_every_phone_in_the_base_identifies_its_own_customer(ready):
    with db.connect_ro() as conn:
        rows = conn.execute("SELECT customer_id, phone FROM customers").fetchall()
    assert len(rows) > 40
    for customer_id, phone in rows:
        assert tools.identify_customer(phone)["customer_id"] == customer_id


def test_identify_customer_returns_only_id_and_first_name(ready):
    assert set(tools.identify_customer("(67) 98543-2109")) == {"customer_id", "first_name"}


# ---------- pedidos do cliente identificado ----------


def test_ana_sees_her_late_shipped_order_in_detail(ready):
    result = tools.get_my_orders(customer_id=ANA)
    assert result["total_orders"] == 1
    assert result["other_orders"] == []
    order = result["order"]
    assert order["order_id"] == 8
    assert order["status"] == "shipped"
    assert order["tracking_code"] == "BRJL5544332BR"
    assert order["estimated_delivery"] == "2026-02-28"
    assert order["total_brl"] == 349.9
    assert order["payment_method"] == "debit"
    assert [(i["product_id"], i["quantity"]) for i in order["items"]] == [(120, 1)]
    assert "Kala" in order["items"][0]["name"]
    assert order["is_late"] is True
    assert order["awaiting_payment"] is False


def test_ana_asking_for_her_order_by_id(ready):
    assert detail(ANA, 8)["order_id"] == 8


def test_ana_cannot_see_the_order_of_another_customer(ready):
    result = tools.get_my_orders(order_id=14, customer_id=ANA)  # pedido do Diego (13)
    assert "error" in result
    assert "order" not in result
    assert "diego" not in all_text(result)


def test_other_customers_order_looks_the_same_as_one_that_does_not_exist(ready):
    """Sem revelar que o pedido existe: a mensagem é idêntica."""
    other = tools.get_my_orders(order_id=14, customer_id=ANA)
    missing = tools.get_my_orders(order_id=9999, customer_id=ANA)
    assert other == missing
    assert "error" in missing


def test_identified_customer_ignores_email_typed_in_chat(ready):
    """Bruno 43 compartilha o e-mail com o Bruno 11, mas o pedido 10 não é dele."""
    result = tools.get_my_orders(order_id=10, email_or_phone="bruno.martins@jmail.com", customer_id=BRUNO_43)
    assert "error" in result
    assert "order" not in result


def test_diego_47_cannot_see_the_order_of_diego_13(ready):
    result = tools.get_my_orders(order_id=14, customer_id=DIEGO_47)
    assert "error" in result
    assert "order" not in result


def test_customer_without_orders_gets_an_empty_result(ready):
    result = tools.get_my_orders(customer_id=30)
    assert "error" not in result
    assert result["total_orders"] == 0
    assert result["order"] is None
    assert result["other_orders"] == []


# ---------- visitante: pedido + e-mail ou telefone, conferidos com o dono ----------


def test_visitor_with_the_owners_email_sees_the_order(ready):
    result = tools.get_my_orders(order_id=14, email_or_phone="diego.castro@coldmail.com")
    assert result["order"]["order_id"] == 14
    assert result["order"]["status"] == "pending"


def test_visitor_gets_only_the_verified_order_and_never_the_customers_total(ready):
    """O Pedro (3) tem os pedidos 1 e 19; o visitante que verifica o 1 não pode nem saber do 19."""
    result = tools.get_my_orders(order_id=1, email_or_phone="pedro.oliveira@jmail.com")  # Pedro tem 1 e 19
    assert set(result) == {"order"}
    assert result["order"]["order_id"] == 1


def test_visitor_email_is_compared_ignoring_case_and_spaces(ready):
    result = tools.get_my_orders(order_id=14, email_or_phone="  Diego.Castro@ColdMail.com ")
    assert result["order"]["order_id"] == 14


def test_visitor_with_the_owners_phone_sees_the_order(ready):
    for phone in ("(67) 98210-9876", "67982109876"):
        assert tools.get_my_orders(order_id=14, email_or_phone=phone)["order"]["order_id"] == 14


def test_visitor_with_the_homonyms_email_is_denied(ready):
    """diego.castro@jmail.com é do Diego 47, não do dono do pedido 14."""
    result = tools.get_my_orders(order_id=14, email_or_phone="diego.castro@jmail.com")
    assert "error" in result
    assert "order" not in result


def test_visitor_with_the_homonyms_phone_is_denied(ready):
    result = tools.get_my_orders(order_id=14, email_or_phone="(67) 99890-7890")
    assert "error" in result
    assert "order" not in result


def test_visitor_with_the_shared_email_gets_the_order_of_its_owner(ready):
    """O e-mail bruno.martins@jmail.com está nos cadastros 11 e 43; o pedido 10 é do 11, então libera."""
    result = tools.get_my_orders(order_id=10, email_or_phone="bruno.martins@jmail.com")
    assert result["order"]["order_id"] == 10


def test_visitor_with_the_phone_of_the_other_bruno_is_denied(ready):
    result = tools.get_my_orders(order_id=10, email_or_phone="(67) 99456-3456")
    assert "error" in result
    assert "order" not in result


def test_visitor_wrong_email_looks_the_same_as_missing_order(ready):
    wrong = tools.get_my_orders(order_id=14, email_or_phone="outra.pessoa@jmail.com")
    missing = tools.get_my_orders(order_id=9999, email_or_phone="outra.pessoa@jmail.com")
    assert wrong == missing


@pytest.mark.parametrize(
    "kwargs",
    [
        {},  # nada
        {"order_id": 14},  # sem e-mail ou telefone
        {"email_or_phone": "diego.castro@coldmail.com"},  # sem pedido: visitante não lista pedidos
        {"order_id": 14, "email_or_phone": ""},
    ],
)
def test_visitor_needs_order_and_contact(ready, kwargs):
    result = tools.get_my_orders(**kwargs)
    assert "error" in result
    assert "order" not in result
    assert "orders" not in result


# ---------- validação e SQL injection ----------


@pytest.mark.parametrize("bad", ["1 OR 1=1", "8; DROP TABLE orders", 1.5, -1, [8], {"id": 8}])
def test_invalid_order_id_is_a_validation_error(ready, bad):
    for kwargs in ({"customer_id": ANA}, {"email_or_phone": "diego.castro@coldmail.com"}):
        result = tools.get_my_orders(order_id=bad, **kwargs)
        assert "error" in result
        assert "order" not in result
    with db.connect_ro() as conn:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 20


def test_email_with_sql_is_only_a_parameter(ready):
    result = tools.get_my_orders(order_id=14, email_or_phone="' OR '1'='1")
    assert "error" in result
    assert "order" not in result
    result = tools.get_my_orders(order_id=14, email_or_phone="%")
    assert "error" in result


# ---------- dados mínimos no retorno ----------


def test_results_never_carry_email_or_phone(ready):
    for result in (
        tools.get_my_orders(customer_id=ANA),
        tools.get_my_orders(order_id=14, email_or_phone="diego.castro@coldmail.com"),
        tools.get_my_orders(customer_id=BRUNO_11),
    ):
        text = all_text(result)
        for forbidden in ("anacarol", "coldmail", "jmail", "99654", "98210", "98543", '"email"', '"phone"'):
            assert forbidden not in text, forbidden


# ---------- ranking (pedidos sintéticos, Pedro com 8 pedidos) ----------


def test_ranking_first_order_is_in_detail_and_the_others_are_summaries(synthetic):
    # Ordem completa de Pedro: aberto 203 (24/03), 201 (20/03), 202 (18/03); entregue há <= 30 dias
    # 204 (10/03), 206 (01/03); o resto 19 (cancelado, 22/02), 205 (entregue há 43 dias), 1 (2025).
    # São 8 pedidos: 1 em detalhe + 5 resumidos; o 205 e o 1 ficam de fora, mas contam em total_orders.
    result = tools.get_my_orders(customer_id=PEDRO)
    assert result["total_orders"] == 8
    assert result["order"]["order_id"] == 203
    assert {(i["product_id"], i["quantity"]) for i in result["order"]["items"]} == {(95, 1), (82, 2)}  # detalhe completo
    assert [o["order_id"] for o in result["other_orders"]] == [201, 202, 204, 206, 19]  # só 5 dos 7 restantes
    assert result["other_orders"][0] == {
        "order_id": 201,
        "order_date": "2026-03-20",
        "status": "pending",
        "products": [result["other_orders"][0]["products"][0]],
    }
    assert "Takamine" in result["other_orders"][0]["products"][0]
    for summary in result["other_orders"]:
        assert set(summary) == {"order_id", "order_date", "status", "products"}


def test_ranking_puts_recent_delivery_before_an_old_one(synthetic):
    # Lucas: o 209 foi entregue há 2 dias; o 4, há 93.
    assert ranking(LUCAS) == [209, 4]


def test_ranking_cancelled_never_beats_open_or_recent(synthetic):
    order = tools.get_my_orders(customer_id=PEDRO)["order"]
    assert order["status"] != "cancelled"
    assert 19 not in ranking(PEDRO)[:4]


# ---------- dias desde a entrega ----------


def test_days_since_delivery_counts_from_the_estimated_delivery(ready, monkeypatch):
    # pedido 7 (cliente 14): entregue, previsão 2026-02-17
    assert detail(14, 7)["days_since_delivery"] == (date(2026, 3, 25) - date(2026, 2, 17)).days
    monkeypatch.setenv("REFERENCE_DATE", "2026-03-10")
    assert detail(14, 7)["days_since_delivery"] == (date(2026, 3, 10) - date(2026, 2, 17)).days


def test_days_since_delivery_only_for_delivered_orders(ready):
    assert detail(ANA, 8)["days_since_delivery"] is None  # enviado
    assert detail(6, 9)["days_since_delivery"] is None  # confirmado
    assert detail(15, 17)["days_since_delivery"] is None  # cancelado


def test_delivered_and_cancelled_orders_are_never_late(ready):
    for customer_id, order_id in ((14, 7), (15, 17), (3, 19)):
        order = detail(customer_id, order_id)
        assert order["is_late"] is False
        assert order["days_late"] == 0
        assert order["expected_by"] is None
        assert order["awaiting_payment"] is False


# ---------- prazos e atrasos em 25/03/2026, conferidos nos CSVs ----------


def test_shipped_order_uses_the_deadline_of_the_order(ready):
    order = detail(ANA, 8)  # enviado, previsão 28/02
    assert order["expected_by"] == "2026-02-28"
    assert order["deadline_source"] == "pedido"
    assert order["delivery_region"] == "metropolitana"
    assert order["is_late"] is True
    assert order["days_late"] == 25


@pytest.mark.parametrize(
    "customer_id, order_id, expected_by, region, days_late",
    [
        (6, 9, "2026-02-25", "metropolitana", 28),  # sex 20/02 + 3 dias úteis
        (11, 10, "2026-03-13", "outras_cidades", 12),  # Três Lagoas: qua 25/02 + 12 dias úteis
        (4, 11, "2026-03-10", "metropolitana", 15),  # qui 05/03 + 3
        (16, 12, "2026-03-13", "metropolitana", 12),  # ter 10/03 + 3
    ],
)
def test_confirmed_orders_use_the_policy_deadline_counted_from_the_order_date(
    ready, customer_id, order_id, expected_by, region, days_late
):
    order = detail(customer_id, order_id)
    assert order["status"] == "confirmed"
    assert order["estimated_delivery"] is None
    assert order["expected_by"] == expected_by
    assert order["deadline_source"] == "politica"
    assert order["delivery_region"] == region
    assert order["is_late"] is True
    assert order["days_late"] == days_late
    assert order["awaiting_payment"] is False


@pytest.mark.parametrize("customer_id, order_id", [(8, 13), (13, 14), (18, 15), (10, 16)])
def test_pending_orders_are_awaiting_payment_and_have_no_deadline(ready, customer_id, order_id):
    order = detail(customer_id, order_id)
    assert order["status"] == "pending"
    assert order["awaiting_payment"] is True
    assert order["expected_by"] is None
    assert order["deadline_source"] is None
    assert order["is_late"] is False
    assert order["days_late"] == 0


def test_shipped_order_with_future_estimate_is_not_late(synthetic):
    order = detail(PEDRO, 202)  # previsão 30/03
    assert order["expected_by"] == "2026-03-30"
    assert order["deadline_source"] == "pedido"
    assert order["is_late"] is False
    assert order["days_late"] == 0


def test_an_order_is_only_late_after_the_expected_date(synthetic):
    order = detail(20, 207)  # previsão = hoje
    assert order["expected_by"] == "2026-03-25"
    assert order["is_late"] is False
    assert order["days_late"] == 0


def test_metro_cities_defaults_to_campo_grande_only(synthetic):
    order = detail(27, 208)  # Dourados, confirmado em 02/03: 12 dias úteis -> 18/03
    assert order["delivery_region"] == "outras_cidades"
    assert order["expected_by"] == "2026-03-18"
    assert order["days_late"] == 7


def test_metro_cities_is_configurable_ignoring_case_accents_and_spaces(synthetic, monkeypatch):
    monkeypatch.setenv("METRO_CITIES", " Dourados , tres lagoas")
    dourados = detail(27, 208)  # 3 dias úteis: 05/03
    assert dourados["delivery_region"] == "metropolitana"
    assert dourados["expected_by"] == "2026-03-05"
    assert dourados["days_late"] == 20
    tres_lagoas = detail(BRUNO_11, 10)  # qua 25/02 + 3 -> 02/03
    assert tres_lagoas["delivery_region"] == "metropolitana"
    assert tres_lagoas["expected_by"] == "2026-03-02"
    assert detail(ANA, 8)["delivery_region"] == "outras_cidades"  # Campo Grande saiu da lista
