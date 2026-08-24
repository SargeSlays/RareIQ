# RareIQ Git Workflow

## One-time setup

1. Put `RareIQ_Git_Setup.ps1` inside your current RareIQ project folder.
2. Open PowerShell in that folder.
3. Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\RareIQ_Git_Setup.ps1
```

The script creates the working branch:

```text
sprint/6.4-recognition-pipeline
```

## Daily workflow

Before changing anything:

```powershell
git status
```

After a tested change:

```powershell
git add .
git commit -m "feat: add pipeline telemetry"
```

Review recent history:

```powershell
git log --oneline --decorate -10
```

## Restore the last committed state

Discard uncommitted code changes:

```powershell
git restore .
```

Remove newly created untracked source files:

```powershell
git clean -nd
```

Review that list first. Then, only when safe:

```powershell
git clean -fd
```

## Sprint rule

Work only on:

```text
Camera frame
→ Card detection
→ Corrected crop
→ OCR
→ Artwork candidates
→ Verification
→ Current Card
→ Session
```

Camera UI, boot flow, branding, and dashboard layout remain frozen during Sprint 6.4.
