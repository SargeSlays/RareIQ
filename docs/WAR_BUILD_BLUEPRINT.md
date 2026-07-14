# RareIQ WAR BUILD Engineering Blueprint

## Mission

Build a fast, local-first, extensible vision platform for collectibles.

## Core Principles

1. Local-first recognition
2. Metadata before heavy assets
3. No duplicate downloads
4. Transparent confidence scoring
5. Every subsystem measurable
6. Plugins instead of hardcoded collectible types
7. Safe resume and graceful shutdown
8. No silent failures

## Current Architecture

### Core
- StorageManager
- PluginManager
- EventBus
- Orchestrator

### Data
- FastPipelineService
- Provider adapters
- UniversalAssetManagerService
- Local catalog and image storage

### Recognition
- GlobalVisualIndexService
- RecognitionFusionService
- OCR and visual candidates

### Quality
- BenchmarkService
- Provider diagnostics
- Asset integrity scan
- Persistent logs

## Plugin Contract

Every collectible plugin defines:

- provider IDs
- normalization schema
- recognition signals
- display name
- plugin version

## Recognition 2.0 Signal Model

- visual similarity: 42%
- collector number: 20%
- OCR name: 12%
- language: 8%
- layout: 7%
- color profile: 6%
- rarity hint: 5%

Weights are explicit and benchmarkable.

## Definition of Done for X.5 Foundation

- Plugin framework exists
- Pokémon runs as a plugin
- Asset registry uses SQLite
- Image integrity scan works
- Recognition fusion is transparent
- Benchmark endpoint works
- WAR ROOM reports subsystem state

## Next Slices

### X.5.1
- Feed real candidate signals into fusion engine
- Persist fused decisions
- Recognition benchmark datasets

### X.5.2
- Collection database and duplicate tracking

### X.5.3
- Creator Studio and browser overlays

### X.5.4
- Pack Battle as a separate mode

### X.5.5
- Pricing and marketplace adapters
