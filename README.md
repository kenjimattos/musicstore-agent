# Empório da Música — agente de atendimento

Agente de atendimento (WhatsApp) da loja Empório da Música, feito em Python com o SDK oficial `anthropic` e um loop de tool use explícito.

> Em construção. O plano de desenvolvimento está em [docs/plano.md](docs/plano.md).

## Como rodar

```bash
cp .env.example .env   # preencha ANTHROPIC_API_KEY
uv run streamlit run app.py
```

## Testes

```bash
uv run pytest            # sem custo, sem API
uv run pytest -m llm     # chama a API
uv run pytest -m e2e     # chama a API
```

Os testes de aceite são ancorados nos dados entregues em `data/`: os valores esperados (preços, promoções, pedidos, clientes) estão escritos nos cenários. Se a loja alterar esses dados, os testes correspondentes falham e os cenários precisam ser atualizados. Os testes nunca escrevem em `data/`: o agente e a ingestão rodam sobre uma cópia temporária, e só `tests/test_scenarios.py` lê o original, para conferir os valores esperados.

## Seções a completar

Arquitetura · Decisões de produto e técnicas · Guardrails e segurança · Como atualizar políticas e dados · Tratamento de dados e suposições · Limitações e próximos passos · Uso de assistentes de IA
