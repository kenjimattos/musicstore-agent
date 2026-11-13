"""Políticas curadas (`data/politicas.md`). Sem LLM.

O agente lê o markdown curado, não o PDF. Estes testes garantem que a curadoria só removeu e
resolveu contradições, sem inventar política, e que nada que conflite com a base ficou no arquivo.

Interface esperada (commit 6):
    policies.load_policies() -> str   # texto de DATA_DIR/politicas.md; cache por mtime, então uma
                                      # edição vale na próxima chamada, sem reiniciar o app
"""

import os
import re
import time

import pypdf
import pytest


@pytest.fixture
def md(store) -> str:
    return (store.data_dir / "politicas.md").read_text(encoding="utf-8")


@pytest.fixture
def pdf_text(store) -> str:
    (pdf,) = store.data_dir.glob("*.pdf")
    text = "\n".join(page.extract_text() for page in pypdf.PdfReader(pdf).pages)
    return _squash(re.sub(r"\(\w+\)", "", text))  # "7 (sete) dias" -> "7dias"


def _squash(text: str) -> str:
    """Sem espaços e em minúsculas: o PDF extrai uma palavra por linha ("3341\\n-\\n4444")."""
    return re.sub(r"\s+", "", text).lower()


# ---------- conteúdo: o que precisa estar ----------


@pytest.mark.parametrize(
    "heading",
    ["horário", "pagamento", "parcelamento", "arrependimento", "defeito", "frete", "promoç", "garantia", "privacidade"],
)
def test_has_the_key_sections(md, heading):
    headings = [line.lower() for line in md.splitlines() if line.startswith("#")]
    assert any(heading in h for h in headings), f"sem seção sobre '{heading}'"


def test_has_the_single_phone_and_email(md):
    assert "3341-4444" in md
    assert re.findall(r"[\w.]+@[\w.]+", md) == ["contato@emporiodamusica.com.br"]
    assert set(re.findall(r"\(67\)\s*\d{4}-\d{4}", md)) == {"(67) 3341-4444"}


def test_has_the_opening_hours(md):
    assert "09:00" in md and "18:00" in md and "13:00" in md


# ---------- fidelidade: nenhum número novo ----------

FACT = re.compile(
    r"R\$\s*\d[\d.]*,\d{2}"  # valores em reais
    r"|\d+\s*%"  # percentuais
    r"|\b\d{2}:\d{2}\b"  # horários
    r"|\b\d+x\b"  # parcelas
    r"|\b\d+(?:\s+a\s+\d+)?\s+(?:dias|horas|meses|anos)\b"  # prazos, inclusive faixas ("5 a 12 dias")
)


def test_every_money_percent_time_and_deadline_exists_in_the_pdf(md, pdf_text):
    facts = FACT.findall(md)
    assert len(facts) >= 20, "poucos números achados: o regex ou o arquivo está errado"
    missing = [f for f in facts if _squash(f) not in pdf_text]
    assert not missing, f"números que não estão no PDF (erro de transcrição?): {missing}"


# ---------- curadoria: o que não pode estar ----------


@pytest.mark.parametrize(
    "forbidden",
    [
        "uso restrito",
        "documento interno",
        "disposições finais",
        "missão",
        "tom de voz",
        "diretrizes de atendimento",
        "fluxo de atendimento",
        "situações especiais",
        "lojas parceiras",
    ],
)
def test_has_no_internal_instructions(md, forbidden):
    assert forbidden not in md.lower()


@pytest.mark.parametrize(
    "conflict",
    [
        "3321-4500",  # telefone divergente da seção 7
        "empóriodamusica",  # e-mail com acento (domínio inválido)
        "cordas orquestrais",  # categorias sem produto na base
        "instrumentos de sopro",
        "volta às aulas",  # campanhas que a base não tem
        "semana do músico",
        "queima de estoque",
        "aniversário da loja (agosto)",
    ],
)
def test_has_nothing_that_conflicts_with_the_data(md, conflict):
    assert conflict not in md.lower()


def test_has_no_catalog_size_claim(md):
    assert not re.search(r"\b300\b", md)


def test_the_only_percentage_is_the_pix_discount(md):
    """As faixas de desconto das campanhas saem: promoção vigente só vem da tool."""
    assert {p.replace(" ", "") for p in re.findall(r"\d+\s*%", md)} == {"5%"}


# ---------- loader: cache por mtime ----------


def test_load_policies_returns_the_file_text(store, md):
    from agent import policies  # import tardio: o módulo nasce no commit 6

    assert policies.load_policies() == md


def test_edit_is_picked_up_when_the_mtime_changes(store):
    from agent import policies  # import tardio: o módulo nasce no commit 6

    path = store.data_dir / "politicas.md"
    policies.load_policies()
    path.write_text("# Nova política\n", encoding="utf-8")
    later = time.time() + 60
    os.utime(path, (later, later))
    assert policies.load_policies() == "# Nova política\n"


def test_file_is_not_reread_while_the_mtime_is_the_same(store):
    from agent import policies  # import tardio: o módulo nasce no commit 6

    path = store.data_dir / "politicas.md"
    original = policies.load_policies()
    mtime = path.stat().st_mtime_ns
    path.write_text("outro texto", encoding="utf-8")
    os.utime(path, ns=(mtime, mtime))
    assert policies.load_policies() == original


def test_installment_rule_for_small_purchases_is_unambiguous(md):
    # o PDF diz "sem valor mínimo de parcela (exceto abaixo de R$ 50,00)", que o modelo pode ler
    # como piso por parcela. A regra é: compra abaixo de R$ 50,00 não parcela.
    assert "exceto abaixo" not in md
    assert re.search(r"abaixo de R\$ 50,00 não (podem|pode) ser parcelad", md)


def test_boundaries_and_deadlines_are_unambiguous(md):
    # valores exatos entram na regra ("a partir de"), e todo prazo diz de quando conta
    assert "a partir de R$ 500,00" in md and "acima de R$ 500" not in md
    assert "a partir de R$ 2.000,00" in md and "acima de R$ 2.000" not in md
    assert "em até 30 dias corridos após o recebimento" in md  # troca por defeito (o PDF diz "após a compra")
    assert re.search(r"em até 7 dias após o recebimento do produto, mediante", md)  # troca por preferência
    assert "30 dias corridos após a compra" not in md


def test_promotion_does_not_remove_defect_or_regret_rights(md):
    assert "A promoção não tira os direitos do cliente" in md
    assert "venda final" in md and "só para troca por preferência" in md
    assert "valor efetivamente pago" in md
    assert "parcela mínima de R$ 100,00" not in md.split("### 3.1")[0]  # resumo da seção 3 não contradiz a 3.1


def test_refund_is_only_promised_for_regret_returns_and_defect_follows_the_manual(md):
    assert "O reembolso da devolução por arrependimento é feito" in md
    assert "contados a partir da confirmação do recebimento da solicitação de devolução pela loja" in md
    assert md.count("reembolso") == 1  # só aqui; o resto é "reembolsadas" (diferença de valor na troca)
    # defeito: vale o manual (30 dias; depois, fabricante, com a loja intermediando), sem prometer o CDC
    assert "Passados os 30 dias, o cliente deve acionar a garantia diretamente com o fabricante" in md
    assert "dentro dos 90 dias da garantia legal, o cliente pode registrar" not in md
