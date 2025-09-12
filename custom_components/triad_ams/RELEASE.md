Releasing Triad AMS (HACS)
==========================

Use this checklist when cutting a new version of the Triad AMS integration.

1) Update version and notes
- Edit `custom_components/triad_ams/manifest.json` → bump the `version` field
- Update `README.md` if user‑visible changes

2) Sanity checks
- Validate basic setup flows (add entry, options, enable/disable outputs)
- Verify routing, volume, and optional input linking/metadata
- Confirm no errors in logs at INFO level during basic actions

3) Commit and tag
- Commit all changes to `main`
- Create an annotated tag matching the manifest version, e.g.:
  - `git tag -a v2025.9.11 -m "Triad AMS v2025.9.11"`
  - `git push --tags`

4) GitHub Release
- Draft a new release for the tag
- Title: `Triad AMS v2025.9.xx`
- Notes: summarize changes, add breaking changes if any
- Publish

HACS notes
- `hacs.json` is present at the repo root with `render_readme: true`
- The integration content lives under `custom_components/triad_ams/`
- No release assets (zip) are required; HACS installs from source

Troubleshooting
- HACS not showing the new version? Make sure the tag is pushed and the version in `manifest.json` matches the tag
- Users stuck with old devices after removing outputs? Ask them to open Options → Save to trigger the built‑in cleanup

