# agent_builder - Documentation

## Overview

Reusable Django app for managing AI agent configurations, instructions, and content blocks. Integrates with the IOLabs platform with multi-tenant support via OAuth2.

## Documentation

- [Deployment Guide](deployment.md) - IOLabs deployment and service management

## Plans

Implementation plans are stored in `Project/plans/` (gitignored):

| Plan | Description |
|------|-------------|
| `2026-03-01-django-app-design.md` | Core design document |
| `2026-03-01-phase1-implementation.md` | Phase 1: CRUD + Apply |
| `2026-03-02-phase2-implementation.md` | Phase 2: Chunks UX + Instructions |
| `2026-03-02-phase3-implementation.md` | Phase 3: Variants + Revisions |
| `2026-03-02-phase4-implementation.md` | Phase 4: Profiles |
| `2026-03-02-import-apply-ui-design.md` | Import/Apply UI design |
| `2026-03-02-import-apply-ui-plan.md` | Import/Apply UI plan |

## Key References

| Item | Location |
|------|----------|
| Django app repo | `/storage/Projects/webapps/IOLabs/AI/django-agent_builder/` |
| GitHub | `chrisfranson/django-agent-builder` |
| IOLabs Python | `/home/chris/.pyenv/versions/iolabs/bin/python` |
| IOLabs project | `/storage/Projects/webapps/IOLabs/iolabs/iolabs/` |
| Test command | `/home/chris/.pyenv/versions/iolabs/bin/python -m pytest tests/ -v` |
