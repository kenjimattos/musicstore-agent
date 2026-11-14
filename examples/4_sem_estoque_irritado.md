# Exemplo 4: Produto sem estoque, cliente irritado

Gerado por `scripts/generate_examples.py` com os cenários de `tests/e2e/scenarios.py` (data simulada 25/03/2026). Abra o trace de cada resposta para ver os guardrails e as ferramentas.

## Produto sem estoque, cliente irritado

_Quem escreve: visitante (número não cadastrado)._

**Cliente:** já é a terceira vez que eu pergunto se o Giannini GF-3D chegou!! cadê??

**Léo:** Poxa, desculpa a demora em te dar uma resposta clara, você tem razão em estar chateado. 🙏

O Giannini GF-3D Dreadnought Sunburst está sem estoque no momento. Não tenho previsão de reposição, então não consigo dizer quando ele volta. Se quiser, eu abro um chamado para a equipe verificar essa data pra você.

Enquanto isso, tenho alternativas que estão à venda:

- Shelby SGD-195E Elétrico Aço Sunburst: R$ 799,00 (R$ 759,05 no PIX), ou 7x de R$ 114,14 sem juros
- Yamaha C70 Nylon Natural: R$ 849,00 (R$ 806,55 no PIX), ou 8x de R$ 106,13
- Tagima Dallas Tuner Aço Natural: R$ 749,00 (R$ 711,55 no PIX), ou 7x de R$ 107,00

O Giannini é um dreadnought de aço, com volume alto e graves bem encorpados, bom pra country e pop. O Shelby é o que mais se aproxima dele, com a mesma pegada de aço e a opção de ser elétrico. Quer que eu abra o chamado para a equipe verificar a reposição do Giannini? 🤘

<details><summary>Trace</summary>

- input_guard: `in_scope`, tom `frustrated` (Cliente pergunta sobre a chegada de um produto (estoque/entrega) e demonstra irritação por ser a terceira vez que pergunta.)
- tool `search_products` `{"query": "Giannini GF-3D", "only_available": false}` → `{"products": [{"product_id": 96, "name": "Giannini GF-3D Dreadnought Sunburst", "category": "Violões", "price_brl": 799.9, "stock_quantity": 0, "availability": "out_of_stock", "promotion": null, "promo_price_brl": null, "pix_price_brl": 759.91, "installments": {"count": 7, "value_brl": 114.27}}], "count": 1, "filters": {"query": "Giannini GF-3D", "only_available": false}}`
- tool `get_product_details` `{"product_id": 96}` → `{"product_id": 96, "name": "Giannini GF-3D Dreadnought Sunburst", "category": "Violões", "price_brl": 799.9, "stock_quantity": 0, "availability": "out_of_stock", "promotion": null, "promo_price_brl": null, "pix_price_brl": 759.91, "installments": {"count": 7, "value_brl": 114.27}, "description": "Violão dreadnought com corpo amplo e acabamento Sunburst. Volume alto e graves profundos, ideal para country e pop.", "specs": {"top": "Spruce", "back_sides": "Sapele", "neck": "Nato", "strings": "steel", "scale": "650mm", "electronics": "no", "color": "Sunburst"}, "alternatives": [{"product_id": 107, …`
- output_guard: `approved`, retries 0, idas ao modelo 3
- critérios de aceite do e2e: ✅ passou

</details>
