"""Políticas da loja: lê `data/politicas.md` (versão curada do manual), com cache por mtime.

O system prompt é montado a cada mensagem e chama `load_policies()`. O arquivo só é relido
quando o mtime muda, então a loja edita o texto e a nova versão vale na próxima mensagem,
sem reiniciar o app.
"""

from agent import db

FILENAME = "politicas.md"

_cache: dict = {"path": None, "mtime_ns": None, "text": ""}


def load_policies() -> str:
    path = db.data_dir() / FILENAME
    mtime_ns = path.stat().st_mtime_ns  # FileNotFoundError claro se a loja apagou o arquivo
    if _cache["path"] != path or _cache["mtime_ns"] != mtime_ns:
        _cache.update(path=path, mtime_ns=mtime_ns, text=path.read_text(encoding="utf-8"))
    return _cache["text"]
