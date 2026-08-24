# RareIQ Paused Work Register

This file records intentionally deferred work so it survives task and context changes.
Review it at least every 20 completed implementation updates.

## Paused

### In-app Help Chat Agent and operations manual

- Status: intentionally deferred; requirements captured only
- Product identity: **Sarge**, RareIQ's integrated voice and help companion
- Goal: add a Help Chat Agent inside RareIQ so operators can ask contextual questions about setup, recognition, cameras, overlays, production tools, inventory, and troubleshooting
- Voice direction: natural low-latency two-way conversation with push-to-talk, interruption support, visible listening/mute state, transcripts, and permission-scoped RareIQ tool actions
- Phone direction: optionally assign Sarge a dedicated telephone number that can be saved as a normal contact and routed through SIP to the realtime voice service; authenticate approved callers by caller ID plus a configurable PIN, expose a clear call-state/audit log, and keep outbound dialing disabled until explicitly configured
- Personality direction: direct, capable, calm under pressure, collaborative, and distinctly RareIQ; do not imitate an existing fictional assistant
- Memory direction: use the version-controlled Obsidian project knowledge base for approved project context, decisions, reminders, and operating documentation
- Knowledge source: ground answers in a maintained RareIQ operations manual rather than improvising product behavior
- Manual scope: installation, first-run setup, camera configuration, single-card and multi-card operation, recognition review, overlays, soundboard, production controls, inventory/QR workflows, diagnostics, recovery, and safety procedures
- Product requirements: context-aware help, links to the relevant screen or manual section, clear uncertainty, no invented controls, offline/manual fallback, searchable history, and a prominent path to human support or diagnostic export
- Documentation requirements: versioned alongside the software, searchable, printable/exportable, accessible from the Help Agent, and updated as features change
- Resume when: the current recognition milestone and physical single-card/12-card validation are stable enough to document accurately
- Next planning step: choose the agent runtime/provider, privacy boundary, offline behavior, knowledge indexing method, and authoring format for the manual

### Live OBS connection and bootstrap

- Status: blocked on external desktop software
- Resume when: OBS Studio is installed and running
- Required OBS setup: Tools → WebSocket Server Settings, enabled on port `4455`
- Then: enter the password in RareIQ, connect, preview the bootstrap plan, and create the six RareIQ scenes
- Safety: preserve existing OBS scenes and sources; bootstrap remains preview-first

## Reminder cadence

- Checkpoint interval: every 20 completed updates
- At each checkpoint: summarize paused items, confirm whether blockers changed, and resume any unblocked item
