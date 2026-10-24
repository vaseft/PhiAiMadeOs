# PhiAiMadeOs (PAMOs) — Repository Agent

This is an **initial GitHub scaffold**. The complete V5.1 Agent Kit is maintained separately until its files are imported. Do not claim this repository contains the full application.

## Product invariants
- Target game: Phira-Pro. Preserve GPL-3.0 obligations for GPL-derived code.
- RPE Next is **PolyForm Noncommercial-1.0.0**, not GPL. Reference its protocols; do not copy/relicense its source into GPL project without a valid legal basis.
- Chart modes: regular animated Phigros chart; true stationary-lane pure 4K / 5K / 6K; special anomaly mode.
- Noise areas: separate future feature, read-only retention in initial model; never auto-generate, mutate or train on them in V1.
- External LLM postprocessor proposes bounded patches, never bypassing validation, version check, independent non-AI audio/geometric audit and human review.
- First target training hardware: RTX 5060 8GB VRAM + 16GB RAM; frozen/cached audio features, staged small models, microbatch 1, checkpointing where needed, actual memory profiling.
- No unsupported claims of training, RPE live editor connection or playability.

## Engineering workflow
1. Import and review complete V5.1 Agent Kit before large feature implementation.
2. Implement reliable format round-tripping and offline MCP tests, then bridge live editor via supported extension API and rollback-capable commit.
3. Add tests for RPE compatibility, pure-key constraints, version conflicts, audit and API patches.
4. Use feature branches, PRs and CI; record upstream commits, test results and capability status.
5. Never commit copyrighted song collections, raw chart packs, secrets, model weights or local GPU caches.

Current scaffold: README, project rules, ignore settings and Codex onboarding. Further files must be brought in from the provided V5.1 package.
