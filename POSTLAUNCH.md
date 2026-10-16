# Post-launch

- Retry algo.AStar with a heuristicScale option to make the heuristic admissible (Phase 0B returned suboptimal paths).
- Trauma levels pending the EMSA PDF; trauma capability for Regional and VMC is not yet level-verified.
- AStar heuristicScale retry (Phase 0B suboptimal paths).
- Trauma levels pending the EMSA PDF.
- Urban stroke bypass numbers: AHA gives none; current limits use the suburban 30 min extra / 45 min total.
- Make record_decision atomic (single transaction) if FalkorDB multi-statement support allows.
- Mutual aid (Santa Clara FD station) and road closures are deferred.
- Backfill OF_KIND on hazards that predate HazardKind (legacy hazard in sjfd) or recreate them through add_hazard.
- Hazard rules are synthetic; replace with vetted fire-service guidance before any real use.
- Trauma levels are shown only; consider level-aware routing for major_trauma.
- Drop the stray empty graph probe_procs (created by phase0/probe_procs.py).
- A CLI command to add hazards (currently ops.add_hazard from Python only).
