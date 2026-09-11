"""Desktop edition edges (PRD-open-hospitality-desktop, docs/desktop/).

Everything in this package is an EDGE around the upstream engine —
packaging, identity issuance, transport. It imports the engine and never
forks it: ingestion, USALI mapping, reporting, tenancy and the disclosure
rules are upstream's, unchanged (PRD §8, "do not fork the engine").

This file and its siblings are additions to csharp36/open-hospitality;
see NOTICE for the Apache-2.0 §4(b) modification statement.
"""
