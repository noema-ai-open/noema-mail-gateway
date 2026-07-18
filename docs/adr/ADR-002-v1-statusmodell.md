# ADR-002: V1-Statusmodell ohne Versandzustände

Status: angenommen (Fable 5, 2026-07-18)

## Kontext

Der initiale Scaffold (`domain.py`) enthielt ein `DraftStatus`-Enum mit
Versandzuständen (`APPROVED`, `SENDING`, `SENT`, …). Version 1 ist strikt
draft-first: „Kein SMTP-Versand ist in Version 1 technisch möglich"
(Abnahmekriterium 5 der CaseBrain-Integration).

Ein Statusmodell, das Versand bereits abbildet, unterläuft diese Garantie:
Code, der `SENT` kennt, lädt dazu ein, den Übergang zu implementieren.

## Entscheidung

Version 1 kennt ausschließlich:

```text
new → staged → synced_to_gmx
synced_to_gmx → modified      (Entwurf wurde extern, z. B. in Thunderbird, geändert)
* → invalidated               (Bindung verletzt, Freigabe-Vorstufe erloschen)
* → failed                    (technischer Fehler, mit error_code im Audit)
```

- Versandzustände existieren in V1 **nicht** — weder im Enum noch im
  Zustandsautomaten. Sie werden erst mit dem separat freizugebenden
  SMTP-Adapter (V2) als eigenes ADR eingeführt.
- Jeder Statusübergang läuft über den Zustandsautomaten in
  `noema-mail-core`; direkte Statuszuweisungen sind verboten.
- `modified` und `invalidated` sind Endzustände für die jeweilige Revision;
  Weiterarbeit erzeugt eine neue Revision mit neuem `content_hash`.

## Konsequenzen

- Der Scaffold-`DraftStatus` wird in M1 ersetzt.
- „Kein Versand möglich" ist strukturell garantiert, nicht nur per Konvention.
