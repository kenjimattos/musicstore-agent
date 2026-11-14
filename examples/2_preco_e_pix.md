# Exemplo 2: Preço e PIX em duas mensagens

Gerado por `scripts/generate_examples.py` com os cenários de `tests/e2e/scenarios.py` (data simulada 25/03/2026). Abra o trace de cada resposta para ver os guardrails e as ferramentas.

## Preço do Takamine GD20 e depois 'e no PIX?' (memória + regra do PIX)

_Quem escreve: visitante (número não cadastrado)._

**Cliente:** Quanto custa o Takamine GD20?

**Léo:** E aí! 🎸 Achei o Takamine GD20 Dreadnought Natural aqui no sistema.

Preço: R$ 2.199,00 no cartão, ou 12x de R$ 183,25 sem juros.
No PIX (à vista, com 5% de desconto): R$ 2.089,05.

Ele está disponível em estoque. Quer saber mais alguma coisa sobre ele ou está procurando outro modelo?

<details><summary>Trace</summary>

- input_guard: `in_scope`, tom `neutral` (Pergunta sobre o preço de um produto da loja.)
- tool `search_products` `{"query": "Takamine GD20", "only_available": false}` → `{"products": [{"product_id": 95, "name": "Takamine GD20 Dreadnought Natural", "category": "Violões", "price_brl": 2199.0, "stock_quantity": 5, "availability": "available", "promotion": null, "promo_price_brl": null, "pix_price_brl": 2089.05, "installments": {"count": 12, "value_brl": 183.25}}], "count": 1, "filters": {"query": "Takamine GD20", "only_available": false}}`
- output_guard: `approved`, retries 0, idas ao modelo 2
- critérios de aceite do e2e: ✅ passou

</details>

**Cliente:** e no PIX?

**Léo:** No PIX ele fica em R$ 2.089,05, à vista. O preço de tabela é R$ 2.199,00, e o desconto de 5% já está aplicado. Ele está em estoque, então dá pra fechar quando quiser. 🤘

<details><summary>Trace</summary>

- input_guard: `in_scope`, tom `neutral` (Pergunta curta de seguimento sobre o preço do Takamine GD20 no PIX, assunto da loja.)
- tool `search_products` `{"query": "Takamine GD20", "only_available": false}` → `{"products": [{"product_id": 95, "name": "Takamine GD20 Dreadnought Natural", "category": "Violões", "price_brl": 2199.0, "stock_quantity": 5, "availability": "available", "promotion": null, "promo_price_brl": null, "pix_price_brl": 2089.05, "installments": {"count": 12, "value_brl": 183.25}}], "count": 1, "filters": {"query": "Takamine GD20", "only_available": false}}`
- output_guard: `approved`, retries 0, idas ao modelo 2
- critérios de aceite do e2e: ✅ passou

</details>
