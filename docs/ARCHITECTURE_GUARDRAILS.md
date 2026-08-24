# RareIQ Architecture Guardrails

These are product contracts, not styling suggestions. Changes that violate
them must fail an automated test before reaching the live studio.

## Active Studio Surface

- `/control` is the production operator surface.
- `control.html`, `studiox.js`, `studiox.css`, and the currently linked Studio X
  styles are the active frontend dependency graph.
- Historical fallback pages are compatibility snapshots. They must not be
  linked by `/control`, imported by active assets, or used as a source for new
  work. Remove a fallback only after route and reference audits prove it has no
  consumer.

## Locked Product Contracts

1. Every right-rail tool is visible through the tool manager, draggable,
   keyboard-orderable, and persisted in local storage.
2. No individual tool—including Identify—has a hard-coded ordering exemption.
3. 3840×2160 is an explicit layout tier. Lower resolutions degrade without
   horizontal clipping or an unbounded camera stage.
4. Candidate artwork uses a verified fallback chain and never renders a broken
   image icon.
5. A provisional candidate is never presented as a verified exact match.
6. Recognition telemetry separates processing time from capture/sample age.

## Change Discipline

- Extend an existing active module before adding another override file.
- Add or update a contract test with every product behavior change.
- Do not delete or rewrite unrelated dirty work.
- Run the focused contract group after every UI or recognition slice.
- Retire legacy code in small, independently reversible batches.
