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
