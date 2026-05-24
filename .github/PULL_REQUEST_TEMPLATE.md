<!-- Thanks for contributing to Ares! Keep PRs focused on one logical change. -->

## What & why

<!-- What does this change, and why? Link any related issue (e.g. "Closes #12"). -->

## Type

<!-- Pick one; match your commit prefix (Conventional Commits). -->

- [ ] feat — new capability
- [ ] fix — bug fix
- [ ] perf — performance
- [ ] test — tests only
- [ ] docs — documentation
- [ ] chore / ci — tooling, build, CI

## How verified

<!-- Which checks did you run? Note hardware/OS if relevant, or "offline/synthetic path". -->

## Checklist

- [ ] **License headers** present on new source files — `python3 scripts/check_license_headers.py`
- [ ] **Backend** compiles and the validation harness is green — `cd backend && python -m compileall -q app tests && python -m tests.test_validation` (`N passed, 0 failed`)
- [ ] **Frontend** tests + build pass (if touched) — `cd frontend && node --test tests/ && npm run build`
- [ ] **No fabricated live data** — synthetic/demo data only as a clearly flagged offline fallback; live paths report empty/`null` honestly
- [ ] **No new GPL/copyleft deps** outside `backend/app/core/sdr/cellular/`; nothing GPL bundled
- [ ] **DSP/DF/IQ stays local & real** — no cloud DSP, no compute stubs
- [ ] Commits are focused and use **Conventional Commit** messages (`feat(scope): …`)
- [ ] Change stays within Ares's **lawful, passive** scope
