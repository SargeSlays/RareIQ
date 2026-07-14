# RareIQ Backend Test Guide

After restarting RareIQ:

## Smoke test

`http://127.0.0.1:8765/api/test/smoke`

## Unified runtime state

`http://127.0.0.1:8765/api/runtime/snapshot`

## Current normalized card

`http://127.0.0.1:8765/api/current-card`

## Recent confirmed pulls

`http://127.0.0.1:8765/api/recent-pulls`

## Submit the latest corrected crop to recognition

Send a POST request to:

`http://127.0.0.1:8765/api/test/recognize-latest-crop`

## Generate a diagnostic report

Send a POST request to:

`http://127.0.0.1:8765/api/test/diagnostic-report`

The response includes the download URL.
