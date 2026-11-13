# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Ingestion of the CSV files into SQLite, run only at startup; older CSVs are rejected.
- Product specs exploded into a filterable table.
- Curated policies file and loader.
- Product search and product details tools.
- Order lookup tool with customer isolation: a visitor sees only the verified order.
- Simulated write tools: data deletion request (LGPD) and escalation to the team.
- Acceptance scenarios (e2e) for the prompt rules.
- Tests for the deterministic output guard (amounts, products, codes, contacts, dates, stock, percentages); red until the implementation lands.

### Fixed

- Purchases below R$ 50 are no longer installable; the installment rule is stated unambiguously.
- Refund applies only to regret returns; defects follow the manual.
- A defect reported after 30 days is handled by the store, and exchange by the manufacturer.
- Ambiguities in the curated policies resolved.
