# X6 Architecture

## Runtime services

- SystemHealthService
- JobQueueService
- LibraryOptimizerService
- GlobalVisualIndexService incremental updater

## Heavy work rule

All maintenance jobs run through one serial queue to avoid:

- duplicate index builds
- simultaneous disk-heavy scans
- competing background jobs
- shutdown races

## Automatic index behavior

Every 60 seconds, RareIQ compares:

- local artwork files
- indexed visual records

When new local artwork exists and no heavy job is running, an incremental index
update is queued automatically.
