# Agent Operating Contract

This repository contains the Environmental Screening & GeoData Operations Platform: a production-style geospatial data platform for preliminary environmental screening over one contained geography. The repository is intended to support semi-autonomous development across many Codex sessions.

## Authority and evidence

- Treat repository code, tests, configuration, executable behavior, and git state as the strongest evidence of current reality.
- Treat `docs/PROJECT_STATE.md` as the factual repository snapshot, `docs/PROJECT_BRIEF.md` as the product scope, `docs/ARCHITECTURE.md` as the architecture record, `docs/DECISIONS.md` as the decision record, and `docs/BACKLOG.md` as the prioritized remaining work.
- Treat `docs/SOURCE_FEASIBILITY.md` as the evidence-backed record of the owner-selected Northern Colorado geography and MVP source direction, artifact-validation status, and any remaining owner decisions. Owner-selected source direction does not mean that exact releases or regional artifacts have passed validation.
- Distinguish verified implementation from intended design, assumptions, and unresolved owner decisions. Do not claim a feature, source, deployment, test, or quality property exists without evidence.
- Read this file and the relevant project documents before changing the repository. Inspect the actual repository state before relying on documentation.

## Normal development loop

1. Read `AGENTS.md` and the relevant documents under `docs/`.
2. Inspect the repository, git status, configuration, tests, and executable behavior.
3. Select the next appropriate objective from `docs/BACKLOG.md`.
4. For substantial work, create a concise plan in `docs/plans/active/`.
5. Implement the objective, including focused tests and necessary refactoring.
6. Validate against `docs/QUALITY_GATES.md`.
7. Review the diff and repository state as if reviewing another developer's work.
8. Correct defects, accidental scope expansion, stale documentation, or misleading claims found during review.
9. Update `PROJECT_STATE.md` and any other documentation changed by reality.
10. Move a completed plan to `docs/plans/completed/` and record its outcome.
11. Commit coherent completed work when git access and task authorization make that appropriate.
12. Continue to the next logically connected task unless a stop condition applies.

Do not stop merely because a task finished, a test failed, an implementation detail was unspecified, or documentation needs updating. Diagnose and fix ordinary problems within scope.

## Decision boundaries and stop conditions

Stop and present the required decision, evidence, realistic options, recommendation, and consequences when work would materially change:

- product scope or the project's intended purpose;
- fundamental architecture or service boundaries;
- environmental datasets or analytical/scientific methodology;
- screening metrics, thresholds, or regulatory-facing language;
- security/privacy posture or authentication model;
- major visual/product direction;
- destructive data behavior or removal of major capabilities;
- paid services or meaningful new operating costs.

Also stop when credentials, permissions, external data, or other unavailable input blocks useful progress; when continuing risks destructive or irreversible changes; when the requested milestone is complete; or when ambiguity is likely to cause substantial rework.

Ordinary implementation choices, low-risk refactoring, test additions, documentation updates, and fixes to failures caused by the current work are authorized.

## Geospatial project toolkit

If `~/projects/geospatial-project-toolkit` is available, treat it as an optional copy/adapt engineering reference for recurring geospatial or software-infrastructure work. Begin with its README, `docs/engineering-standard.md`, and `docs/pattern-inventory.md`, then inspect only relevant patterns.

Use toolkit code as copy/adapt reference only. The project repository, requirements, tests, and documented decisions remain authoritative. Do not force a pattern into this project, and do not create imports, symlinks, submodules, package dependencies, or other runtime coupling to the toolkit. Do not modify the toolkit during ordinary project work. Adapted code becomes normal project-owned code.

Do not add toolkit references to product documentation; mention them in technical development documentation only when materially relevant.

## Git and documentation behavior

- Inspect `git status` before editing and preserve unrelated user changes.
- Keep commits coherent and reasonably scoped; use descriptive messages; validate before committing.
- Never discard work, rewrite published history, or force-push without explicit authorization.
- Repository documentation is part of the implementation. Update it in the same work unit when reality changes.
- Keep plans concise and disposable. Active plans belong in `docs/plans/active/`; completed plans belong in `docs/plans/completed/` with the final outcome recorded.

## Completion standard

Before declaring work complete, apply the relevant checks in `docs/QUALITY_GATES.md`, including data and geospatial validation where applicable. State what was actually verified, what remains unverified, and any known limitations.
