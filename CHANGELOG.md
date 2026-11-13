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
