# Landing artboards (throwaway)

Ten single-file HTML prototypes for the Landing redesign — wayfinder #184, under #181.

**These are throwaway.** They are not React, not wired to the app, and not imported by anything.
Only the winning direction gets ported into `frontend/src/routes/Landing/`; the rest of this
directory can be deleted once that happens.

```
artboards/*.html   ten standalone documents (a1…d2), each a complete page
build.py           inlines all ten into artboards.html (the published Artifact)
artboards.html     generated — do not edit by hand
```

Rebuild after editing any artboard:

```bash
python3 prototypes/landing/build.py
```

Findings, the Cyrillic specimen judgement and the caveats live in `docs/research/landing-artboards.md`.
