# RareIQ v0.2 — Session Engine

This build moves RareIQ from a single-script prototype into a modular application.

## New in v0.2

- Orchestrator
- Event bus
- Session service
- Customer → order → product → box → pack → card structure
- Manual operator controls
- Next/previous pack
- Next/previous box
- Start/close customer batch
- Pack counter overlay
- Green glow and sound when a new pack starts
- Running card count, hit count, and estimated value
- All overlays receive the same synchronized event
- TikTok portrait-first data panel

## Architecture

```text
RareIQ Orchestrator
├── Event Bus
├── Session Service
├── Experience Service
├── Pricing Service (placeholder)
├── Vision Service
└── Web / Overlay Layer
```

Most of RareIQ is deterministic software. AI models will be added where judgment or recognition is needed.

## Run

1. Install Python 3.11 or newer.
2. Extract the folder.
3. Double-click `start.bat`.
4. Open:
   `http://127.0.0.1:8765/control`

## TikTok Live Studio

Add local browser/web sources if supported by your workflow:

- Data panel:
  `http://127.0.0.1:8765/overlay/data`
- Pack counter:
  `http://127.0.0.1:8765/overlay/pack`
- Full-screen effects:
  `http://127.0.0.1:8765/overlay/fx`
- Card border:
  `http://127.0.0.1:8765/overlay/card`
- Audio:
  `http://127.0.0.1:8765/overlay/audio`

If TikTok Live Studio will not load localhost browser sources directly, capture the overlay window or route it through a local browser window. A native RareIQ transparent-window output is on the roadmap.

## What to test

1. Create a customer batch.
2. Set boxes and packs per box.
3. Click Next Pack.
4. Confirm the pack widget flashes green.
5. Trigger demo card rarities.
6. Confirm totals update.
7. Click Next Box and Close Customer.
