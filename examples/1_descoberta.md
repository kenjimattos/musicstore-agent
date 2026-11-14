# Exemplo 1: Descoberta: violão até R$ 1.000

Gerado por `scripts/generate_examples.py` com os cenários de `tests/e2e/scenarios.py` (data simulada 25/03/2026). Abra o trace de cada resposta para ver os guardrails e as ferramentas.

## Descoberta: violão até R$1000, depois MPB

_Quem escreve: visitante (número não cadastrado)._

**Cliente:** Quero um violão até R$1000

**Léo:** E aí! 🎸 Pra eu te indicar o certo, me conta: que som você quer tirar? Mais MPB e bossa, ou algo mais pop/rock? E você já toca há quanto tempo? 🤘

<details><summary>Trace</summary>

- input_guard: `in_scope`, tom `neutral` (Cliente pergunta por violão dentro da faixa de preço, assunto de produtos da loja.)
- output_guard: `approved`, retries 0, idas ao modelo 1
- critérios de aceite do e2e: ✅ passou

</details>

**Cliente:** Toco MPB e bossa nova

**Léo:** Massa, pra MPB e bossa o nylon é o caminho certo! 🎸 Aqui estão os violões de nylon disponíveis até R$ 1.000:

- Yamaha C70 Nylon Natural: R$ 849,00. No PIX sai R$ 806,55, ou 8x de R$ 106,13. É o mais encorpado da lista.
- Giannini GN-15 Nylon Cedro Natural: R$ 689,00. No PIX R$ 654,55, ou 6x de R$ 114,83. Tampo de cedro, boa projeção.
- Yamaha C40 Nylon Natural: R$ 599,90. No PIX R$ 569,91, ou 6x de R$ 99,98. Clássico de estudo, muito confiável.
- Rozini RC-104 Nylon Estudante: R$ 459,90. No PIX R$ 436,91, ou 5x de R$ 91,98.
- Tagima Memphis AC-39 Nylon Natural: R$ 429,90. No PIX R$ 408,41, ou 5x de R$ 85,98.

Pra você, que toca bossa, qual é o seu nível? Se já toca com pegada, o C70 ou o GN-15 valem muito a pena. Se está começando, o C40 é uma escolha segura. Quer que eu detalhe algum deles? 🤘

<details><summary>Trace</summary>

- input_guard: `in_scope`, tom `neutral` (Cliente responde à pergunta do atendente sobre o estilo musical para indicar um violão dentro do orçamento.)
- tool `search_products` `{"query": "violão", "max_price": 1000, "specs": {"strings": "nylon"}}` → `{"products": [{"product_id": 83, "name": "Tagima Memphis AC-39 Nylon Natural", "category": "Violões", "price_brl": 429.9, "stock_quantity": 15, "availability": "available", "promotion": null, "promo_price_brl": null, "pix_price_brl": 408.41, "installments": {"count": 5, "value_brl": 85.98}}, {"product_id": 85, "name": "Rozini RC-104 Nylon Estudante", "category": "Violões", "price_brl": 459.9, "stock_quantity": 10, "availability": "available", "promotion": null, "promo_price_brl": null, "pix_price_brl": 436.91, "installments": {"count": 5, "value_brl": 91.98}}, {"product_id": 128, "name": "Kala …`
- output_guard: `approved`, retries 0, idas ao modelo 2
- critérios de aceite do e2e: ✅ passou

</details>
