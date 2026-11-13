"""Tools de produto (busca, detalhes, categorias). Sem LLM, sobre a cópia temporária de `data/`.

Interface esperada (commit 8). Toda tool devolve um dict; erro de validação vira `{"error": "..."}`
(o modelo lê a mensagem e se corrige na iteração seguinte), nunca uma exceção:

    tools.search_products(query=None, category=None, specs=None, min_price=None, max_price=None,
                          only_available=True) -> {
        "products": [item, ...],            # até 10
        "count": int,
        "filters": {...},                   # filtros aplicados, para o modelo relaxar numa busca vazia
        "count_without_specs": int,         # só quando `specs` foi usado: quantos casariam sem ele
    }
    tools.get_product_details(product_id) -> item + {"description", "specs": {...}, "alternatives": [item, ...]}
    tools.list_categories() -> {"categories": [{"name", "product_count"}, ...]}  # só status active; inclui vazias

    item = {
        "product_id", "name", "category", "price_brl", "stock_quantity",
        "availability": "available" | "out_of_stock" | "discontinued" | "coming_soon",
        "promotion": {"discount_percent", "description"} | None,   # só is_active=1; várias -> a maior
        "promo_price_brl": float | None,
        "pix_price_brl": float | None,      # 5% sobre o preço de tabela; None se há promoção (não acumula)
        "installments": {"count": int, "value_brl": float},   # parcelamento máximo sem juros (regra 3.1),
    }                                                         # sobre o preço efetivo (promocional, se houver)

Os valores derivados vêm daqui, nunca de conta do LLM: é o que sustenta o output_guard.
"""

import pytest

from agent import db, ingest, tools


@pytest.fixture
def ready(store):
    ingest.ingest_all()
    return store


def by_id(result, product_id):
    return next((p for p in result["products"] if p["product_id"] == product_id), None)


def ids(result):
    return {p["product_id"] for p in result["products"]}


def table_count(table):
    with db.connect_ro() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ---------- busca: texto, categoria, preço, disponibilidade ----------


def test_search_by_name_ignores_case_and_accents(ready):
    result = tools.search_products(query="TAKAMINE gd20")
    assert ids(result) == {95}
    assert tools.search_products(query="violao")["count"] > 0  # "Violão" na descrição


def test_search_filters_by_category_and_price(ready):
    result = tools.search_products(category="Ukuleles", max_price=300)
    assert result["count"] > 0
    assert all(p["category"] == "Ukuleles" and p["price_brl"] <= 300 for p in result["products"])
    assert tools.search_products(category="violoes", min_price=5000)["count"] >= 1  # sem acento, sem case


def test_search_returns_at_most_ten(ready):
    assert len(tools.search_products()["products"]) == 10


def test_search_hides_unavailable_by_default(ready):
    result = tools.search_products(category="Violões")
    assert 96 not in ids(result)  # ativo, estoque 0
    assert 113 not in ids(result)  # descontinuado
    assert all(p["availability"] == "available" for p in result["products"])


def test_search_can_include_unavailable(ready):
    result = tools.search_products(category="Violões", only_available=False, min_price=700, max_price=800)
    assert by_id(result, 96)["availability"] == "out_of_stock"
    assert by_id(result, 113)["availability"] == "discontinued"


def test_coming_soon_is_not_available(ready):
    assert 130 not in ids(tools.search_products(category="Ukuleles"))
    result = tools.search_products(category="Ukuleles", only_available=False, min_price=1700)
    assert by_id(result, 130)["availability"] == "coming_soon"


# ---------- preços derivados: promoção, PIX, parcelas ----------


def test_active_promotion_sets_discounted_price(ready):
    item = by_id(tools.search_products(query="Taylor 110e"), 94)
    assert item["price_brl"] == 5999
    assert item["promotion"] == {"discount_percent": 8, "description": "Desconto Exclusivo"}
    assert item["promo_price_brl"] == pytest.approx(5519.08, abs=0.01)


def test_pix_does_not_stack_with_promotion(ready):
    item = by_id(tools.search_products(query="Taylor 110e"), 94)
    assert item["pix_price_brl"] is None


def test_pix_is_five_percent_off_list_price_without_promotion(ready):
    item = by_id(tools.search_products(query="Takamine GD20"), 95)
    assert item["promotion"] is None and item["promo_price_brl"] is None
    assert item["pix_price_brl"] == pytest.approx(2199 * 0.95, abs=0.01)


def test_inactive_promotions_are_ignored(ready):
    # o produto 96 tem duas promoções (18% e 40%), ambas inativas
    item = by_id(tools.search_products(query="Giannini GF-3D", only_available=False), 96)
    assert item["promotion"] is None


def test_best_active_promotion_wins(ready):
    # promoção extra e ativa, maior que a de 8% do produto 94
    path = next(ready.data_dir.glob("*promotions.csv"))
    text = path.read_text(encoding="utf-8")
    path.write_text(text + ("" if text.endswith("\n") else "\n") + "900,94,25,Teste,1\n", encoding="utf-8")
    ingest.ingest_all()
    item = by_id(tools.search_products(query="Taylor 110e"), 94)
    assert item["promotion"]["discount_percent"] == 25
    assert item["promo_price_brl"] == pytest.approx(5999 * 0.75, abs=0.01)


def test_installments_follow_rule_3_1(ready):
    # R$ 599,90: 7x daria R$ 85,70 (< R$ 100); 6x dá R$ 99,98 (>= R$ 80) -> máximo 6x
    cheap = by_id(tools.search_products(query="Yamaha C40"), 81)
    assert cheap["installments"]["count"] == 6
    assert cheap["installments"]["value_brl"] == pytest.approx(599.9 / 6, abs=0.01)
    # R$ 2.199,00: 12x dá R$ 183,25 (>= R$ 100) -> 12x
    dear = by_id(tools.search_products(query="Takamine GD20"), 95)
    assert dear["installments"] == {"count": 12, "value_brl": pytest.approx(2199 / 12, abs=0.01)}


def test_purchase_below_50_is_not_installable_and_up_to_3x_has_no_minimum():
    # regra 3.1: abaixo de R$ 50 não parcela; até 3x não há parcela mínima
    assert tools._installments(49.9) == {"count": 1, "value_brl": 49.9}
    assert tools._installments(50) == {"count": 3, "value_brl": pytest.approx(16.67, abs=0.01)}
    assert tools._installments(200) == {"count": 3, "value_brl": pytest.approx(66.67, abs=0.01)}  # 4x seria R$ 50 (< R$ 80)


def test_installments_use_the_promotional_price(ready):
    item = by_id(tools.search_products(query="Taylor 110e"), 94)
    assert item["installments"]["count"] == 12
    assert item["installments"]["value_brl"] == pytest.approx(item["promo_price_brl"] / 12, abs=0.01)


# ---------- filtro por specs ----------


def test_specs_filter_finds_nylon_guitar_and_not_ukulele(ready):
    result = tools.search_products(category="Violões", specs={"strings": "nylon"})
    assert 111 in ids(result)
    assert all(p["category"] == "Violões" for p in result["products"])
    assert "filters" in result


def test_specs_pairs_are_anded(ready):
    result = tools.search_products(category="Violões", specs={"strings": "nylon", "electronics": "yes"})
    assert 111 in ids(result)
    assert 81 not in ids(result)  # nylon, mas sem captação
    only_nylon = tools.search_products(category="Violões", specs={"strings": "nylon"})
    assert result["count"] < only_nylon["count"]


def test_specs_match_ignores_case_and_accents(ready):
    exact = tools.search_products(category="Violões", specs={"top": "Spruce Sólido"})
    loose = tools.search_products(category="Violões", specs={"top": "spruce solido"})
    assert exact["count"] > 0 and ids(exact) == ids(loose)
    assert ids(tools.search_products(category="Violões", specs={"strings": "NYLON"})) == ids(
        tools.search_products(category="Violões", specs={"strings": "nylon"})
    )


def test_unknown_spec_key_lists_valid_keys(ready):
    result = tools.search_products(category="Violões", specs={"cor_favorita": "azul"})
    assert "error" in result
    assert "strings" in result["error"] and "electronics" in result["error"]


def test_unknown_spec_value_lists_valid_values(ready):
    result = tools.search_products(category="Violões", specs={"strings": "titanio"})
    assert "error" in result
    assert "nylon" in result["error"] and "steel" in result["error"]


def test_empty_search_reports_filters_and_count_without_specs(ready):
    # nylon + eletroacústico existe, mas nenhum custa menos de R$ 100
    result = tools.search_products(category="Violões", specs={"strings": "nylon"}, max_price=100)
    assert result["products"] == [] and result["count"] == 0
    assert result["filters"]["specs"] == {"strings": "nylon"}
    assert result["filters"]["max_price"] == 100
    assert result["count_without_specs"] == 0
    wider = tools.search_products(category="Violões", specs={"strings": "nylon", "electronics": "yes"}, max_price=1000)
    assert wider["count"] == 0
    assert wider["count_without_specs"] > 0  # sem `specs` há violões até R$ 1.000: o modelo pode relaxar


# ---------- validação e segurança ----------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"specs": "nylon"},  # não é objeto
        {"specs": {"strings": 6}},  # valor não é texto
        {"specs": {"strings": ["nylon"]}},
        {"min_price": -1},
        {"max_price": "caro"},
        {"query": "x" * 201},
        {"category": "Teclados e Pianos; DROP TABLE products"},  # categoria desconhecida
    ],
)
def test_invalid_arguments_return_an_error(ready, kwargs):
    assert "error" in tools.search_products(**kwargs)


def test_unknown_category_error_lists_valid_names(ready):
    assert "Violões" in tools.search_products(category="Gaitas")["error"]


def test_sql_injection_in_query_is_inert(ready):
    products_before = table_count("products")
    result = tools.search_products(query="'; DROP TABLE products; --")
    assert result["products"] == []
    assert table_count("products") == products_before


def test_sql_injection_in_specs_is_inert(ready):
    result = tools.search_products(specs={"strings": "nylon' OR '1'='1"})
    assert "error" in result  # valor desconhecido: nunca vira SQL
    assert table_count("product_specs") > 0


@pytest.mark.parametrize("wildcard", ["_", "%%", "a%"])
def test_like_wildcards_are_escaped(ready, wildcard):
    result = tools.search_products(query=wildcard, only_available=False)
    assert result["count"] == 0  # nenhum nome ou descrição contém esses caracteres literais


def test_lone_percent_matches_only_the_literal_character(ready):
    # só a descrição do produto 140 tem "%" ("100% Birch"); sem escape, voltaria o catálogo inteiro
    result = tools.search_products(query="%", only_available=False)
    assert ids(result) == {140}


# ---------- get_product_details ----------


def test_details_include_specs_and_description(ready):
    item = tools.get_product_details(111)
    assert item["name"].startswith("Rozini RV-175")
    assert item["specs"]["strings"] == "nylon"
    assert item["specs"]["electronics"] == "yes"  # o JSON original, sem normalizar
    assert "captação" in item["description"]
    assert item["alternatives"] == []  # disponível: sem alternativas


def test_details_of_out_of_stock_product_offer_alternatives(ready):
    item = tools.get_product_details(96)
    assert item["availability"] == "out_of_stock"
    assert item["alternatives"]
    assert all(a["category"] == "Violões" and a["availability"] == "available" for a in item["alternatives"])
    assert 96 not in {a["product_id"] for a in item["alternatives"]}


def test_details_of_discontinued_product_offer_alternatives(ready):
    item = tools.get_product_details(113)
    assert item["availability"] == "discontinued"
    assert item["alternatives"]
    assert all(a["category"] == "Violões" and a["availability"] == "available" for a in item["alternatives"])


def test_details_of_coming_soon_product(ready):
    assert tools.get_product_details(130)["availability"] == "coming_soon"


def test_details_unknown_or_invalid_id(ready):
    assert "error" in tools.get_product_details(99999)
    assert "error" in tools.get_product_details("1 OR 1=1")
    assert "error" in tools.get_product_details(-3)


# ---------- list_categories ----------


def test_list_categories_counts_active_products_and_keeps_empty_ones(ready):
    cats = {c["name"]: c["product_count"] for c in tools.list_categories()["categories"]}
    assert len(cats) == 9
    assert cats["Violões"] == 34  # 35 no CSV, menos o descontinuado (113); o 96 é ativo, só sem estoque
    assert cats["Ukuleles"] == 14  # menos o 130, em breve
    assert cats["Instrumentos de Sopro (Madeiras)"] == 0
    assert cats["Instrumentos de Sopro (Metais)"] == 0
    assert cats["Cordas Orquestrais"] == 0


# ---------- ordem: o que está à venda vem antes ----------


def test_available_products_come_before_unavailable_ones(ready):
    # sem o filtro, um "em breve" mais barato não pode ficar na frente de produto à venda (nem ocupar a vaga dele)
    result = tools.search_products(category="Ukuleles", only_available=False)
    order = [p["availability"] == "available" for p in result["products"]]
    assert by_id(result, 130)["availability"] == "coming_soon"
    assert order == sorted(order, reverse=True), "disponíveis precisam vir antes dos demais"


def test_within_each_group_the_order_is_still_by_price(ready):
    result = tools.search_products(category="Ukuleles", only_available=False)
    for group in (True, False):
        prices = [p["price_brl"] for p in result["products"] if (p["availability"] == "available") is group]
        assert prices == sorted(prices)
