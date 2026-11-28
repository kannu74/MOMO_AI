"""Momo's security layers for the web and email (Phase 3).

Layer 1 - information check + egress control (egress.py, tools/info.py)
    Only allowlisted hosts, only the topic is sent out, only the few sentences that answer the question are kept
    (context minimisation). Email can only go to EMAIL_CONTACTS.
Layer 2 - prompt-injection defence (extractor.py, backend/core.py, backend/persona.py)
    Web text goes through a plain-code structured extractor (sanitise, drop instruction-like sentences, keep
    relevant facts) and reaches the LLM only inside <external_data trust="untrusted">, escaped. Only the system
    prompt is trusted. The LLM that reads web data has no tools; web data never reaches the router.
Layer 3 - action control (outbox.py, main_ui.py)
    Momo may fetch news for your topics on her own, but can never send email by herself: every email waits for
    you to press Approve in the window (not by voice). Recipients are re-checked at send time.
Audit log: audit.py -> `security_events` table.
"""
