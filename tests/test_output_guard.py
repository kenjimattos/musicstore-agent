"""Output guard determinístico: todo fato verificável da resposta precisa ter fonte. Sem LLM.

Interface esperada (commit 12):

    guards.output_guard(text, tool_results, policies) -> guards.Verdict
        text          resposta do agente
        tool_results  resultados (dicts) das tools chamadas NO TURNO ATUAL; o de turnos anteriores
                      não conta como fonte, então o modelo precisa consultar de novo
        policies      texto de `politicas.md`
        Verdict.ok          True se todo fato tem fonte
        Verdict.violations  lista de mensagens objetivas, uma por fato sem fonte, citando o valor
                            (vão como feedback para o retry do agente)

Fontes válidas: resultados de tools do turno e texto das políticas. Verificados: valores em R$,
nomes de produto do catálogo, códigos (rastreio, protocolos LGPD/ATD), números de pedido, datas,
prazos em dias, quantidades de estoque, percentuais, telefones e e-mails. O guard consulta o
catálogo (`db`) só para reconhecer nomes de produto.
"""

import pytest

from agent import guards, ingest, policies, tools

ANA = 2  # pedido 8: enviado, atrasado, rastreio BRJL5544332BR, previsão 28/02
TAKAMINE = "Takamine GD20 Dreadnought Natural"  # produto 95: R$ 2.199,00, PIX R$ 2.089,05, 12x de R$ 183,25


@pytest.fixture
def ready(store):
    ingest.ingest_all()
    return store


@pytest.fixture
def pol(ready):
    return policies.load_policies()


@pytest.fixture
def takamine(ready):
    return tools.search_products(query="takamine gd20")


@pytest.fixture
def order8(ready):
    return tools.get_my_orders(customer_id=ANA)


def check(text, results, pol):
    return guards.output_guard(text, results, pol)


def assert_blocked(verdict, *fragments):
    assert not verdict.ok
    joined = " ".join(verdict.violations)
    for fragment in fragments:
        assert fragment in joined, f"{fragment!r} não aparece em {verdict.violations}"


# ---------- sem fatos verificáveis ----------


def test_greeting_without_facts_passes(pol):
    assert check("Fala, Ana! Tudo certo? Em que posso ajudar? 🎸", [], pol).ok


def test_verdict_is_clean_when_ok(pol):
    verdict = check("Bora tocar! 🤘", [], pol)
    assert verdict.ok and verdict.violations == []


# ---------- valores em R$ ----------


def test_prices_from_tool_pass(takamine, pol):
    text = f"O {TAKAMINE} está R$ 2.199,00, ou R$ 2.089,05 no PIX. Dá pra pagar em 12x de R$ 183,25."
    assert check(text, [takamine], pol).ok


def test_price_without_cents_matches(takamine, pol):
    assert check(f"O {TAKAMINE} sai por R$ 2.199.", [takamine], pol).ok


def test_invented_price_fails(takamine, pol):
    assert_blocked(check(f"O {TAKAMINE} está R$ 1.850,00.", [takamine], pol), "1.850,00")


def test_price_off_by_a_real_fails(takamine, pol):
    assert_blocked(check(f"O {TAKAMINE} está R$ 2.198,00.", [takamine], pol), "2.198,00")


def test_installment_value_invented_fails(takamine, pol):
    assert_blocked(check(f"{TAKAMINE} em 12x de R$ 180,00.", [takamine], pol), "180,00")


def test_price_computed_by_the_model_fails(takamine, pol):
    # 10% de desconto "de cabeça" sobre 2.199,00; nenhuma tool devolveu esse valor
    assert_blocked(check(f"Fazendo 10% fica {TAKAMINE} por R$ 1.979,10.", [takamine], pol), "1.979,10")


def test_values_in_policies_pass(pol):
    assert check("O frete é R$ 35,00 abaixo de R$ 500,00, e acima disso é grátis.", [], pol).ok


def test_price_with_no_tool_result_fails(pol):
    assert_blocked(check("Esse violão custa R$ 10,00.", [], pol), "10,00")


def test_price_from_another_turn_does_not_count(takamine, pol):
    # só os resultados do turno atual são fonte: o preço da consulta antiga não vale
    assert_blocked(check("Custa R$ 2.199,00.", [{"categories": []}], pol), "2.199,00")


# ---------- produtos ----------


def test_product_from_tool_passes(takamine, pol):
    assert check(f"Tenho o {TAKAMINE}, um violão com som encorpado.", [takamine], pol).ok


def test_product_match_ignores_case_and_accents(takamine, pol):
    assert check(f"Tenho o {TAKAMINE.upper()}.", [takamine], pol).ok


def test_catalog_product_not_consulted_fails(takamine, pol):
    other = tools.search_products(query="kala ka-c")["products"][0]["name"]
    assert_blocked(check(f"Eu indico o {other}.", [takamine], pol), other)


def test_product_in_alternatives_passes(ready, pol):
    details = tools.get_product_details(96)  # sem estoque: traz alternativas da mesma categoria
    alternative = details["alternatives"][0]["name"]
    assert check(f"Esse acabou, mas tenho o {alternative}.", [details], pol).ok


def test_product_in_order_items_passes(order8, pol):
    assert check("Seu pedido é o Kala KA-C Concert Mogno.", [order8], pol).ok


def test_product_name_in_policies_text_is_not_a_source(takamine, pol):
    # o catálogo não é política: sem consulta, o nome não tem fonte
    assert_blocked(check("Temos o Kala KA-C Concert Mogno.", [], pol), "Kala KA-C Concert Mogno")


# ---------- códigos e números ----------


def test_tracking_code_from_tool_passes(order8, pol):
    assert check("O rastreio é BRJL5544332BR.", [order8], pol).ok


def test_invented_tracking_code_fails(order8, pol):
    assert_blocked(check("O rastreio é BR123456789BR.", [order8], pol), "BR123456789BR")


def test_order_number_from_tool_passes(order8, pol):
    assert check("Sobre o pedido 8: ele está a caminho.", [order8], pol).ok
    assert check("O pedido #8 está a caminho.", [order8], pol).ok


def test_order_number_not_consulted_fails(order8, pol):
    assert_blocked(check("Seu pedido 14 está a caminho.", [order8], pol), "14")


def test_numbered_list_after_the_word_pedido_is_not_an_order_number(pol):
    # o "2." da lista, na linha seguinte a "pedido", não é o pedido 2 (falso positivo visto no e2e)
    text = "Pra eu localizar sua compra, me manda:\n1. O número do pedido\n2. O e-mail ou telefone do cadastro"
    assert check(text, [], pol).ok
    assert check("Me passa o número do pedido\n- e o e-mail do cadastro", [], pol).ok


def test_order_number_on_the_same_line_is_still_checked(pol):
    assert_blocked(check("Seu pedido nº 14 está a caminho.", [], pol), "14")
    assert_blocked(check("O pedido #14 saiu.", [], pol), "14")


def test_escalation_protocol_from_tool_passes(ready, pol):
    ticket = tools.escalate_to_team("atraso", "Pedido 8 atrasado", 8, customer_id=ANA)
    assert check(f"Abri o chamado {ticket['protocol']}. Retorno até 24 horas úteis.", [ticket], pol).ok


def test_invented_ticket_protocol_fails(ready, pol):
    ticket = tools.escalate_to_team("atraso", "Pedido 8 atrasado", 8, customer_id=ANA)
    assert_blocked(check("Abri o chamado ATD-000999.", [ticket], pol), "ATD-000999")


def test_deletion_protocol_from_tool_passes(ready, pol):
    request = tools.request_data_deletion(customer_id=ANA, thread_id="t1")
    assert check(f"Registrei seu pedido, protocolo {request['protocol']}.", [request], pol).ok


def test_invented_deletion_protocol_fails(ready, pol):
    request = tools.request_data_deletion(customer_id=ANA, thread_id="t1")
    assert_blocked(check("Protocolo LGPD-000777.", [request], pol), "LGPD-000777")


def test_protocol_without_tool_call_fails(pol):
    assert_blocked(check("Seu protocolo é ATD-000001.", [], pol), "ATD-000001")


# ---------- identificadores duráveis do cliente (`known`, de tools.known_identifiers) ----------
# Número do pedido, rastreio e protocolo do próprio cliente valem em qualquer turno; o volátil
# (preço, estoque, status, atraso) continua exigindo consulta no turno.

KNOWN_ANA = {"protocols": ["ATD-000001"], "orders": [8], "tracking": ["BRJL5544332BR"]}


def check_known(text, pol, known=KNOWN_ANA):
    return guards.output_guard(text, [], pol, known=known)


def test_customers_protocol_from_an_earlier_turn_passes(pol):
    assert check_known("Seu chamado ATD-000001 continua aberto.", pol).ok


def test_protocol_not_among_the_customers_fails(pol):
    assert_blocked(check_known("Seu chamado é o ATD-000002.", pol), "ATD-000002")


def test_customers_order_number_from_an_earlier_turn_passes(pol):
    assert check_known("Registrei sua reclamação sobre o pedido 8.", pol).ok


def test_order_number_not_among_the_customers_fails(pol):
    assert_blocked(check_known("Seu pedido 14 está a caminho.", pol), "14")


def test_customers_tracking_code_from_an_earlier_turn_passes(pol):
    assert check_known("O código de rastreio é BRJL5544332BR.", pol).ok


def test_tracking_code_not_among_the_customers_fails(pol):
    assert_blocked(check_known("O código de rastreio é BRXX1234567BR.", pol), "BRXX1234567BR")


def test_volatile_facts_still_need_a_query_this_turn(pol):
    # o pedido 8 é conhecido, mas total, atraso e data não: podem ter mudado
    verdict = check_known("O pedido 8 custou R$ 349,90 e está 25 dias atrasado desde 28/02.", pol)
    assert_blocked(verdict, "349,90", "25 dias", "28/02")


# ---------- contatos ----------


def test_store_contacts_from_policies_pass(pol):
    assert check("Liga pra gente: (67) 3341-4444, ou escreve para contato@emporiodamusica.com.br.", [], pol).ok


def test_divergent_phone_fails(pol):
    assert_blocked(check("Liga pra gente: (67) 3321-4500.", [], pol), "3321-4500")


def test_invented_email_fails(pol):
    assert_blocked(check("Escreve para vendas@emporiodamusica.com.br.", [], pol), "vendas@emporiodamusica.com.br")


def test_phone_format_does_not_matter(pol):
    assert check("O número é 6733414444.", [], pol).ok


# ---------- datas, prazos, estoque, percentuais ----------


def test_delivery_date_from_tool_passes(order8, pol):
    assert check("A previsão era 28/02, então já passou do prazo.", [order8], pol).ok
    assert check("A previsão era 28/02/2026.", [order8], pol).ok


def test_invented_delivery_date_fails(order8, pol):
    assert_blocked(check("Deve chegar em 10/03.", [order8], pol), "10/03")


def test_return_deadline_from_tool_passes(ready, pol):
    ticket = tools.escalate_to_team("reclamacao", "Cliente reclama", customer_id=ANA)
    assert check(f"A equipe retorna {ticket['return_deadline']}.", [ticket], pol).ok


def test_policy_deadlines_pass(pol):
    assert check("Você tem até 7 dias após o recebimento para devolver.", [], pol).ok


def test_invented_deadline_fails(pol):
    assert_blocked(check("A entrega leva até 20 dias úteis.", [], pol), "20 dias")


def test_stock_quantity_from_tool_passes(takamine, pol):
    assert check(f"Tenho 5 unidades do {TAKAMINE}.", [takamine], pol).ok


def test_invented_stock_quantity_fails(takamine, pol):
    assert_blocked(check(f"Tenho 12 unidades do {TAKAMINE} em estoque.", [takamine], pol), "12 unidades")


def test_pix_percentage_passes(takamine, pol):
    assert check("No PIX você ganha 5% de desconto.", [takamine], pol).ok


def test_active_promotion_percentage_passes(ready, pol):
    promoted = next(p for p in tools.search_products(max_price=100000)["products"] if p["promotion"])
    percent = promoted["promotion"]["discount_percent"]
    assert check(f"Está com {percent}% de desconto.", [{"products": [promoted]}], pol).ok


def test_invented_percentage_fails(takamine, pol):
    assert_blocked(check("Faço 30% de desconto pra você.", [takamine], pol), "30%")


# ---------- feedback e vários fatos ----------


def test_every_violation_is_reported(takamine, pol):
    verdict = check(f"{TAKAMINE} por R$ 1.850,00, rastreio BR123456789BR.", [takamine], pol)
    assert len(verdict.violations) == 2
    assert_blocked(verdict, "1.850,00", "BR123456789BR")


def test_same_invented_value_is_reported_once(pol):
    verdict = check("Custa R$ 10,00. Repito: R$ 10,00.", [], pol)
    assert len(verdict.violations) == 1
