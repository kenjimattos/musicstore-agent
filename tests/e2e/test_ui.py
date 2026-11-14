"""UI (`app.py`) com o Streamlit AppTest: headless, sem navegador.

O painel do avaliador não chama a API e roda no pytest padrão. O chat chama o agente (API) e é `-m e2e`.

Contrato da UI:
- sidebar: selectbox "Simular conversa como" com o customer_id como valor (None = visitante),
  rótulo "Nome (Cidade)"; botão "Nova conversa";
- painel do avaliador na sidebar: tabela de pedidos do cliente (coluna "Pedido"), solicitações de
  exclusão e chamados; para o visitante, uma dica de teste com o pedido 14;
- chat: st.chat_input; cada resposta do agente tem um expander com o trace (guard, tools, output_guard);
- trocar o cliente ou clicar em "Nova conversa" limpa a conversa.
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[2] / "app.py")
ANA, DIEGO = 2, 13


@pytest.fixture
def app(store):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    return at


def select(at, customer_id):
    at.sidebar.selectbox[0].select(customer_id).run()
    assert not at.exception, at.exception


def orders_in_panel(at) -> list[int]:
    return [int(v) for v in at.sidebar.dataframe[0].value["Pedido"].tolist()] if at.sidebar.dataframe else []


# ---------- sem API ----------


def test_app_starts_with_the_visitor_and_the_simulated_date(app):
    assert app.sidebar.selectbox[0].value is None  # visitante
    assert any("25/03/2026" in m.value for m in app.info), "aviso da data simulada no topo"
    assert any("pedido 14" in m.value for m in [*app.sidebar.caption, *app.sidebar.info]), "dica de teste do visitante"


def test_selector_lists_customers_by_name_and_city(app):
    options = app.sidebar.selectbox[0].options
    assert "Visitante (número não cadastrado)" in options
    assert "Ana Carolina Ferreira (Campo Grande)" in options
    # cadastros parecidos aparecem separados (indexados pelo customer_id, não pelo nome)
    assert len([o for o in options if o.startswith("Bruno")]) >= 2


def test_panel_shows_only_the_selected_customers_orders(app):
    select(app, ANA)
    assert orders_in_panel(app) == [8]
    select(app, DIEGO)
    assert orders_in_panel(app) == [14]


def test_panel_says_it_is_not_sent_to_the_model(app):
    select(app, ANA)
    text = " ".join(m.value for m in [*app.sidebar.caption, *app.sidebar.markdown])
    assert "não é enviado ao agente" in text


# ---------- com API (-m e2e) ----------


@pytest.fixture
def api():
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY ausente: o chat chama a API")


@pytest.mark.e2e
def test_identified_customer_is_greeted_and_the_trace_is_shown(app, api):
    select(app, ANA)
    app.chat_input[0].set_value("oi, tudo bem?").run()
    assert not app.exception, app.exception
    replies = [m for m in app.chat_message if m.name == "assistant"]
    assert replies, "a resposta do agente aparece no chat"
    assert "Ana" in " ".join(md.value for md in replies[-1].markdown)
    assert any("Trace" in e.label for e in app.expander), "expander com o trace da resposta"


@pytest.mark.e2e
def test_switching_customer_clears_the_conversation(app, api):
    select(app, ANA)
    app.chat_input[0].set_value("oi").run()
    assert [m for m in app.chat_message if m.name == "assistant"]
    select(app, DIEGO)
    assert not app.chat_message, "trocar de cliente começa uma conversa nova"
