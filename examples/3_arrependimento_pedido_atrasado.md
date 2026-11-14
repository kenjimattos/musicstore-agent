# Exemplo 3: Arrependimento com pedido atrasado

Gerado por `scripts/generate_examples.py` com os cenários de `tests/e2e/scenarios.py` (data simulada 25/03/2026). Abra o trace de cada resposta para ver os guardrails e as ferramentas.

## Ana (identificada) se arrependeu: pedido 8 enviado e atrasado

_Quem escreve: Ana (cliente identificado pelo telefone)._

**Cliente:** me arrependi da compra, posso devolver?

**Léo:** Oi, Ana! Vi aqui o seu pedido do Kala KA-C Concert Mogno. Ele ainda não consta como entregue, então o prazo de 7 dias para arrependimento só começa a contar quando você receber. Ou seja, o direito continua valendo na chegada.

Se a sua ideia é desistir antes de receber, isso é tratado como cancelamento, e eu encaminho para a equipe. Quer que eu faça isso?

Também preciso te pedir desculpas: o pedido está atrasado em 25 dias em relação à previsão de 28/02. Se quiser, abro um chamado para a equipe acompanhar a entrega.

<details><summary>Trace</summary>

- input_guard: `in_scope`, tom `neutral` (Cliente pergunta sobre devolução de compra, assunto da loja.)
- tool `get_my_orders` `{}` → `{"total_orders": 1, "order": {"order_id": 8, "order_date": "2026-02-15", "status": "shipped", "total_brl": 349.9, "payment_method": "debit", "tracking_code": "BRJL5544332BR", "estimated_delivery": "2026-02-28", "notes": null, "items": [{"product_id": 120, "name": "Kala KA-C Concert Mogno", "quantity": 1}], "days_since_delivery": null, "delivery_region": "metropolitana", "expected_by": "2026-02-28", "deadline_source": "pedido", "policy_deadline": null, "awaiting_payment": false, "is_late": true, "days_late": 25}, "other_orders": []}`
- output_guard: `approved`, retries 0, idas ao modelo 2
- critérios de aceite do e2e: ✅ passou

</details>
