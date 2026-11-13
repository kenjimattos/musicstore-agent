"""Helpers de texto compartilhados pelos testes de aceite."""

import re
import unicodedata

BRL = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)")


def norm(text: str) -> str:
    """Minúsculas e sem acento, para comparar palavras."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def brl_values(text: str) -> list[float]:
    """Valores em R$ do texto, como float (aceita '2.199,00', '599,9' e '1000')."""
    return [float(m.replace(".", "").replace(",", ".")) for m in BRL.findall(text)]


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


NEGATIONS = {"nao", "nem", "nenhum", "nenhuma", "sem", "nunca"}
NEGATION_WINDOW = 4  # palavras antes da frase


def affirms(text: str, phrase: str) -> bool:
    """True se `phrase` aparece em `text` sem uma negação nas NEGATION_WINDOW palavras antes.

    "seu pedido está atrasado" afirma "atrasado"; "não aparece nenhum atraso" e "não consigo dar uma
    nova data" não afirmam. Para checar promessa e acusação, não vazamento (vazamento usa not_mention).
    """
    words = re.findall(r"\w+", norm(text))
    target = re.findall(r"\w+", norm(phrase))
    n = len(target)
    for i in range(len(words) - n + 1):
        if words[i:i + n] == target and not NEGATIONS & set(words[max(0, i - NEGATION_WINDOW):i]):
            return True
    return False
