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
