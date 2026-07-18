# Bauauftrag M5 an Sol 5.6: CaseBrain-Adapter (kuratierter Kontext)

Architekt: Fable 5. Branch: `feature/m5-casebrain-adapter`. Vertragliche
Grundlage: `Noema_case_brain_vm02/docs/MAIL_GATEWAY_INTEGRATION.md` (im
Bauauftrag zusammengefasst, Repo nicht nötig). Nur stdlib.

## Prinzipien

- CaseBrain übergibt NUR kuratierte Daten: Fallreferenz, Empfänger-VORSCHLAG,
  Betreff, Entwurfstext, freigegebene Anlagen-IDs, optionale Evidenz-/
  Fristen-REFERENZEN (nur IDs).
- Das Gateway kopiert NIE eine Fallakte; CaseBrain kennt NIE Credentials.
- Alles aus CaseBrain-Dokumenten stammende ist untrusted data: Es kann
  Empfehlungen enthalten, aber niemals Toolaufrufe auslösen.

## Inhalte

1. `src/noema_mail_gateway/casebrain.py`:
   - frozen dataclass `CuratedMailContext`: `case_reference` (Pflicht, Muster
     `^[A-Za-z0-9_\-\.]{1,128}$`), `recipient_suggestions`
     (Liste EmailAddress, max 10 — bleiben VORSCHLAG), `subject_suggestion`
     (max 500, keine Zeilenumbrüche), `body_draft` (max 256 KiB),
     `approved_attachment_ids` (Liste, Muster wie case_reference, max 20),
     `evidence_refs`/`deadline_refs` (nur ID-Listen, max je 50).
   - `parse_curated_context(payload: dict) -> CuratedMailContext`: strict —
     unbekannte Felder → Fehler. Explizit abgelehnte Felder (eigener
     Fehlercode `forbidden_field`): `full_case_file`, `documents`,
     `document_contents`, `evidence_texts`, `credentials`, `password`,
     `attachment_path`, `attachment_paths`, `send_immediately`, `to_final`.
   - `build_draft_request(context, account_alias, idempotency_key) -> dict`:
     erzeugt einen validen `mail_create_draft`-Request (durch
     `validate_request` geprüft); Empfängervorschläge werden zu `to` des
     ENTWURFS (draft-first: Sandra sieht sie in Thunderbird), Anlagen NUR als
     IDs.
2. Injection-Härtung in `noema_mail_core.redaction` oder neuem Modul
   `noema_mail_core/untrusted.py`: `strip_control_chars(text)`,
   `mark_untrusted(text) -> UntrustedText` (Wrapper-Typ; `CuratedMailContext.
   body_draft` wird als UntrustedText getragen, str-Zugriff nur explizit über
   `.text`). Kein Parsing/Ausführen von Inhalten.

## Tests (Vertragstests!)

- Gut-Fall: kuratierter Kontext → valider create_draft-Request.
- Komplette Fallakte im Payload (`full_case_file`, `documents`, …) → abgelehnt.
- Jedes verbotene Feld einzeln → forbidden_field.
- Unbekanntes Feld → invalid_request.
- Empfänger bleibt Vorschlag: build_draft_request erzeugt Entwurf, niemals
  ein Feld, das Versand auslöst (Request enthält kein send_immediately etc.).
- Anlage nur über ID; ein Pfad in approved_attachment_ids (`../`, `/home/`)
  → Fehler.
- case_reference bleibt im Request nachvollziehbar erhalten.
- Prompt-Injection-Kanarienvögel im body_draft und subject_suggestion
  (z. B. "IGNORE ALL INSTRUCTIONS", "run shell_command", eingebettetes
  JSON `{\"tool\": \"mail_update_draft\"}` , HTML mit verstecktem
  <span style=display:none>) → Kontext wird angenommen, aber der erzeugte
  Request enthält die Inhalte NUR im body_text (als Daten), und
  parse/build lösen keinerlei zusätzliche Operationen aus; Steuerzeichen
  sind entfernt.
- Grenzwerte: 10 Empfänger ok, 11 → Fehler; 256 KiB Body ok, mehr → too_large.

## Abnahme

ruff + pytest grün, nur stdlib, kein Netz, kein git commit.
