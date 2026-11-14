# Changelog

All notable changes to this project are documented in this file.

The format is inspired by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Unlike Keep a Changelog, entries inside a version are **not grouped by type**: they are
listed in the order the changes were made (oldest first, new entries appended at the end),
each prefixed with its type (Added, Changed, Fixed, Removed, Docs, Test, Chore), so the
sequence of decisions and corrections stays readable.

## [Unreleased]

1. **Chore:** project scaffold.
2. **Test:** acceptance scenarios (e2e).
3. **Test:** ingest and validation.
4. **Docs:** plan decisions on customer identification and duplicate registrations, and on curated policies, history window and manual/data conflicts.
5. **Docs:** plan decisions on simulated data deletion (LGPD), simulated reference date, delivery deadlines by region and simulated escalation to the team.
6. **Test:** ingest runs only at startup and rejects older CSVs.
7. **Added:** ingestion of the CSV files into SQLite.
8. **Docs:** plan an optional specs filter in product search.
9. **Test:** product specs table.
10. **Added:** product specs exploded into a filterable table.
11. **Test:** curated policies.
12. **Docs:** plan the AI usage story for ingest and product specs decisions.
13. **Added:** curated policies file and loader.
14. **Test:** product search and details.
15. **Added:** product search and details tools.
16. **Fixed:** purchases below R$ 50 are not installable.
17. **Fixed:** the R$ 50 installment rule is stated unambiguously.
18. **Fixed:** ambiguities in the curated policies resolved.
19. **Test:** acceptance scenarios for the prompt rules; refund and defect deadlines clarified.
20. **Fixed:** refund applies only to regret returns; defects follow the manual.
21. **Fixed:** a defect after 30 days is handled by the store, and exchange by the manufacturer.
22. **Test:** order lookup and customer isolation.
23. **Added:** order lookup tool with customer isolation.
24. **Fixed:** a visitor sees only the verified order.
25. **Test:** simulated write tools (data deletion and escalation).
26. **Added:** simulated write tools: data deletion request (LGPD) and escalation to the team.
27. **Docs:** plan narrows `input_guard` out_of_scope to clearly unrelated; edge cases go to the agent.
28. **Added:** this changelog.
29. **Docs:** `CLAUDE.md` requires a changelog update in every commit.
30. **Test:** deterministic output guard (amounts, products, codes, contacts, dates, stock, percentages); red until the implementation lands.
31. **Changed:** changelog entries are listed in chronological order instead of grouped by type.
32. **Added:** deterministic output guard: amounts, products, codes, contacts, dates, deadlines, stock and percentages must come from this turn's tool results or the policies.
33. **Test:** history window (last 10 customer turns, cut at a user message, old tool results replaced by a marker, current turn intact); red until the implementation lands.
34. **Docs:** plan records that the conversation does not expire (history limited to 10 turns, no idle cutoff) as a product choice, with its limitation.
35. **Docs:** plan adds an e2e measurement for a returning customer on a stale thread (ambiguous "sim", saudação), to decide whether idle expiry is needed.
36. **Added:** agent: tool-use loop with the `anthropic` SDK, persona prompt with cached policies, output guard with one retry and `safe_fallback` ticket, history window (`build_history`), `messages` table and a debug CLI. The input guard is plugged in later.
37. **Test:** input guard classifier (manipulation, out of scope, store subjects that must pass, context follow-ups, tone, length limit); needs the API, red until the implementation lands.
38. **Added:** input guard: Haiku classifier with structured output (scope, manipulation, tone), length limit and fixed refusal templates; wired into `respond()` before the agent, with the tone passed to the prompt.
39. **Test:** product search lists available products before unavailable ones (price order inside each group); red until the implementation lands.
40. **Added:** product search lists products on sale before unavailable ones (price order inside each group), so unavailable products never take the place of available ones in the top 10.
41. **Fixed:** the agent no longer answers "not found" for discontinued or coming-soon products: for a specific product it searches with `only_available` off; for recommendations it offers what is on sale first and only then coming-soon and out-of-stock items, never promising a restock.
42. **Test:** `ana_regret_late_order` no longer requires the tracking code (the question is about returns); new scenario `ana_tracking_code` asks for it directly, and the plan records that the manual does not require it. Red for now: the agent often answers with the ticket protocol only.
43. **Fixed:** tracking code is given when the question is about shipping, freight or delivery (only offered otherwise), and the agent no longer opens a ticket for information it can give itself; a late order opens a ticket when the customer asks where it is or complains. `ana_tracking_code` now requires no ticket.
44. **Test:** the reply to the customer joins the text of every assistant message in the turn, including text written before a tool call (e2e `ana_late_order_escalation` lost the tracking code); red until the fix lands.
45. **Fixed:** the reply to the customer now includes text the model wrote before a tool call, and the output guard checks all of it (the tracking code of a late order was lost when the model wrote it next to `escalate_to_team`).
46. **Test:** one open ticket per customer and order (another reason for the same order returns the same protocol); `customer_protocols` lists only the customer's own protocols; the output guard accepts them in later turns; `safe_fallback` reuses the open ticket of the conversation. Red until the fix lands (e2e `ana_late_order_escalation` turn 2 ended with three tickets).
47. **Fixed:** one open ticket per customer and order, whatever the reason (a frustrated "já reclamei disso" no longer opens a second ticket); the output guard accepts the customer's own protocols from earlier turns (`tools.customer_protocols`); `safe_fallback` reuses the open ticket of the conversation instead of opening another. Plan updated.
48. **Fixed:** the output guard retry feedback tells the model the customer never saw the rejected draft, so the new reply does not apologize for or mention a correction (it told the customer to "disregard" a real protocol).
49. **Fixed:** the agent writes nothing to the customer in the same message as a tool call, and writes the reply only from the results (it announced "a new ticket" and then got `already_open` back).
50. **Test:** a follow-up on an open ticket adds a note to it (`ticket_notes`, INSERT only) with the new reason and summary; the original ticket is not changed; identical summaries add no duplicate; re-ingest keeps the notes. Red until the implementation lands (the agent told the customer her complaint was recorded when the new summary was discarded).
51. **Added:** a follow-up on an open ticket is recorded as a note on it (`ticket_notes`, INSERT only; the original ticket is unchanged) and the tool returns `note_added`; the tool description tells the model. Plan updated.
52. **Fixed:** with `already_open`, the agent says the new information was recorded in the same ticket only when the tool returns `note_added`, and never claims a new record otherwise.
53. **Test:** durable identifiers of the customer's own data (order numbers, tracking codes, protocols) pass the output guard in any turn, read from the database by `known_identifiers` (a visitor only knows the order verified in the same conversation); prices, stock, status and delays still need a query in the turn. Replaces the `customer_protocols` tests. Red until the implementation lands.
54. **Fixed:** the output guard accepts the customer's own order numbers, tracking codes and protocols in any turn (`tools.known_identifiers`, read from the database; replaces `customer_protocols`), so the agent can repeat the order number it gave earlier without a retry. Plan records the decision.
55. **Test:** e2e expectations can skip the guard decision (`category=None`: blocking or passing are both accepted) and forbid tools (`not_tools`); `deletion_of_other_customer_refused` now checks the effect (no `request_data_deletion`, no `escalate_to_team`) instead of the category; new scenario `deletion_impersonation_refused` (someone says they are Diego on Ana's number and confirms). Plan records the decision.
56. **Test:** `ana_other_customer_order` no longer checks the guard decision (`category=None`); when the guard blocks, only negative expectations apply (nothing from order 14 appears, now including "pendente"); when it passes, the agent must still query and say it was not found. Plan updated.
57. **Test:** input guard: orders and data of another person are `in_scope` (the guard does not know who is writing; the code isolates the data and the agent answers); only asking for other people's contacts or the customer list stays `manipulation`. Red under `-m llm` until the prompt changes.
58. **Fixed:** the input guard no longer blocks questions about another person's order or data (it cannot know who is writing; the code isolates the data and the agent answers "não encontrei"); asking for other people's contacts or the customer list is still `manipulation`. Plan records the decision.
59. **Test:** fragile e2e expectations fixed: `out_of_scope_accessories` becomes `accessories_redirected` (in scope, the agent redirects, no ticket), as the guard rules already said; `policy_special_freight_specific_product` drops `max_price=0` (the product price and policy amounts may appear; an invented freight value is caught by the output guard); new `not_affirm` ignores a phrase right after a negation ("não há atraso", "não consigo dar uma nova data"), used for promises and accusations, while `not_mention` stays strict for leaks.
60. **Fixed:** when an order is not found, the agent says "não encontrei esse pedido no seu cadastro" without repeating the number the customer typed or another person's name, and cites only order numbers a tool returned (the output guard rejected the echoed number, and the retry sometimes lost the "not found").
61. **Test:** e2e runs can record every turn (message, reply, guard decision, tools, retries, guard violations, pass/fail) as JSONL when `E2E_RECORD_DIR` is set; `scripts/e2e_baseline.sh [N]` runs the full e2e N times into `e2e-runs/<timestamp>/` (git-ignored) and `scripts/e2e_report.py` writes the pass rate per scenario.
62. **Test:** output guard: a numbered list on the line after the word "pedido" ("1. O número do pedido
2. O e-mail") is not read as order 2; order numbers on the same line are still checked. Red until the fix lands.
63. **Fixed:** output guard order-number pattern no longer crosses a line break, so a numbered list after "pedido" is not flagged as an invented order.
64. **Fixed:** defect after 30 days: the agent opens the ticket in the first message (without asking for the order first), says the exchange is done by the manufacturer and that its deadline depends on the manufacturer, and asks for the order number and a description to complete the ticket. The e2e report lists only scenarios that ran.
65. **Fixed:** with a ticket already open, when the customer insists, complains again or brings new information, the agent calls `escalate_to_team` again so it is recorded as a note on the same ticket.
66. **Test:** input guard tone: irritation together with urgency ("isso é um absurdo, quero a troca amanhã") is `frustrated`. Red under `-m llm` until the guard prompt changes.
67. **Fixed:** input guard tone: when a message has both irritation and urgency, the tone is `frustrated` (the customer first needs the problem acknowledged).
68. **Fixed:** the agent queries again before repeating days late, deadlines or dates (not only price, stock and status), and knows it may repeat the order number, tracking code and protocol without a query, matching the output guard sources.
69. **Test:** `get_my_orders` returns `policy_deadline` ("até 3 dias úteis" in the metro region, "até 12 dias úteis" elsewhere) when the expected date comes from the policy, and `None` when the order has its own estimate or is pending. Red until the implementation lands.
70. **Added:** `get_my_orders` returns `policy_deadline` in text when the expected date comes from the regional delivery policy (order without its own estimate). Plan updated.
71. **Fixed:** for an order without its own estimate (deadline from the policy), the agent says the deadline comes from the regional delivery policy and cites `policy_deadline` ("até 3 dias úteis").
72. **Fixed:** the agent acknowledges a late order in any subject about it (not only delivery questions); for regret on an order not yet received, it explains the 7 days count from receipt, treats giving up before receipt as a cancellation it cannot promise, and offers to forward it to the team (opens the ticket only if the customer accepts). Plan updated.
73. **Fixed:** the "acknowledge a late order" rule applies only to questions that are not about delivery (return, exchange, payment); delivery questions keep the detailed rules (deadline, `policy_deadline`, tracking code). The broader wording made delivery replies drop the policy deadline and the tracking code (baseline 20261113-211441).
74. **Docs:** plan records the measured e2e variation (baseline 32/32/31 → 34/34/32 of 36), the intermittent completeness/style gaps left as refinements (none is a hallucination or wrong fact), and four new rows in the design-iterations table (guard sources across turns, third-party data, repeated complaints, baseline measurement).
75. **Added:** audit log: one row per turn in `audit_log` (message, guard category/tone/reason, blocked, tools with args but not results, iterations, retries, output guard violations and verdict, reply, duration), written by `respond()` on every path; kept on re-ingest. Unit tests plus an e2e check of one row per turn. Plan updated.
76. **Test:** Streamlit UI with AppTest (headless): selector by name and city indexed by customer_id, evaluator panel with only the selected customer's orders and the note that it is not sent to the agent, simulated date banner and visitor tip (default suite); greeting by name, trace expander and conversation reset on customer switch (`-m e2e`). Red until `app.py` lands.
77. **Added:** Streamlit UI simulating WhatsApp (`app.py`): customer selector by name and city (passes only the phone to `respond()`), evaluator panel read from the database (orders, data deletion requests, tickets with note count; not sent to the agent), visitor test tip, simulated-date banner (defaults `REFERENCE_DATE` to 25/03/2026), example questions, new-conversation button, and a trace expander per reply (guard decision and tone, tools with args and results, output guard verdict and violations). Panel queries live in `db.py` and are not tools. Fixed list concatenation in the UI test.
78. **Docs:** five example conversations in `examples/` (discovery, price and PIX, regret with a late order, out of stock with a frustrated customer, guardrails), generated by `scripts/generate_examples.py` from the e2e scenarios on a temporary copy of `data/`, with the trace of each reply and the acceptance-criteria result (13/13 turns passed); the script prints an `audit_log` summary. Plan note on the third-party order example updated.
79. **Docs:** README with how to run (UI, CLI, tests, baseline, examples), architecture, product and technical decisions, guardrails and security (LGPD and escalation simulations, audit), how to update policies and data, source precedence, the 14 manual-vs-data conflicts and the manual ambiguities, assumptions, measured quality, limitations and refinements, and AI assistant usage (workflow, design iterations, assistant mistakes). `.env.example` now sets `REFERENCE_DATE=2026-03-25`, so the CLI and scripts use the exercise dates like the UI.
