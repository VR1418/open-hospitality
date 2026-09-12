"""The owner's own AI (PRD §6.3, ADR-D7).

The owner supplies the provider and the key; we never hold one, never proxy a
request and never take a margin. Nothing in here is on a write path: a
suggestion is a proposal, and a person applies it.
"""
