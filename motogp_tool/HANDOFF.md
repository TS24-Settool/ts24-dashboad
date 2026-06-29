# MotoGP Performance Analysis — Handoff (remote → local)

Branch: `claude/motogp-analysis-tool-comparison-h5y802` (also pushed to `main`).
Deploys to Streamlit Cloud from `main`. Entry app: repo-root `dashboard.py`
(nav reduced to **MotoGP Performance Analysis** + **Accounts**; login kept).

## Why this handoff
The remote (web) sandbox **cannot reach MotoGP servers**
(`api.motogp.pulselive.com`, `resources.motogp.com`, `mgp-timings.teknichrono.fr`,
`overpass-api.de` all return 403 from the egress proxy). So the **online-fetch
path was written but never live-tested**. A LOCAL machine has open internet and
can verify/fix it directly — that's the #1 task.

## Package map (`motogp_tool/`)
- `parse_analysis_pdf.py` — parse official "Analysis" PDF → per-lap/per-sector.
  **Proven** (real race: 25 riders / 422 flying laps). T1+T2+T3+T4 == lap time.
- `engine.py` — classification, ideal lap, head-to-head sector deltas, is_flying.
- `app_page.py` — the Streamlit page (`render_motogp_page`). Tabs: Classification
  / Head-to-Head / Track Map / Lap Detail. Data sources: PDF upload, demo,
  online fetch, GPS/GeoJSON trace upload, Timekeeping-Plan upload.
- `fetch_official.py` — **OFFICIAL PulseLive** client (UNVERIFIED). Cascade
  `/seasons → /events → /categories → /sessions → /session/{uuid}/classification`,
  then `files.analysis` (or swap `file` …Classification.pdf→Analysis.pdf) →
  download PDF → our parser.
- `fetch.py` — old third-party mgp-timings client (unreliable; superseded).
- `parse_timekeeping_plan.py` — parse official "Timekeeping Points Plan" PDF →
  FL/IP1/IP2/IP3 GPS = exact 4-sector boundary positions. **Works.**
- `circuit_map.py` — circuit geometry + delta colouring. `boundaries_from_timing`
  (GPS → exact splits), `fetch_osm` (Overpass, unverified), `build_track_figure`,
  `build_shape_figure`, GeoJSON/GPX trace → `outline_from_lonlat`.
- `circuits/*.json` — bundled racing-ordered layouts (losail, mugello, portimao,
  barcelona, circuit-of-the-americas, red-bull-ring, silverstone) + `assen.json`
  (traced from the Timekeeping Plan; `"ordered": false` → shown as shape+markers,
  not sector-coloured, because a traced outline isn't in racing order).

## Works (verified in remote)
- Upload official Analysis PDF → full analysis (the reliable path).
- Classification / Head-to-Head / Lap Detail.
- Track Map for the 7 bundled circuits (racing-ordered → sector colouring).
- Timekeeping-Plan upload → exact boundaries on a racing-ordered layout.
- GPS lap-trace upload (GPX / CSV / **GeoJSON**, incl. OSM raceway exports).

## Broken / unverified (DO THIS LOCALLY)
1. **Online fetch.** Symptom on Cloud: "N riders · 0 flying laps" (that was the
   OLD mgp-timings adapter). The new `fetch_official.py` is unverified.
   - Run locally, e.g.:
     ```python
     from motogp_tool import fetch_official as F
     sid = F.season_id(2025); evs = F.events(sid)
     ev = next(e for e in evs if e["short_name"]=="JPN")
     cat = next(c for c in F.categories(ev["id"]) if "Moto3" in c["name"])
     ses = next(s for s in F.sessions(ev["id"], cat["id"]) if s["type"]=="RAC")
     print(F.analysis_pdf_url(ses["id"], ev.get("test")))   # <- inspect real URL
     df,label,slug = F.fetch_session(2025, ev, cat, ses, ev["name"], "RAC")
     print(label, len(df), int(df["is_flying"].sum()))
     ```
   - Print the raw classification JSON to confirm field names (`files.analysis`
     vs `file`) and that the derived Analysis PDF URL is correct + downloadable.
     Fix `fetch_official.py` to match reality, then it "just works".
2. **Auto-load on login** (`_auto_load_once` / `_latest_race`) depends on #1.
3. **OSM `fetch_osm`** for non-bundled circuits — verify Overpass works on the
   target host; otherwise rely on the GeoJSON/GPX upload (works) or bundle more
   circuits from overpass-turbo exports.

## Deploy gotcha (important)
Streamlit Cloud keeps the **old container** for an active user until it reboots;
new commits don't swap in until **Manage app → Reboot app** (or the container is
recycled). A build marker — `build: official-source v3` under the page title —
tells you which version is live. The user kept seeing old builds for this reason.

## Suggested next steps (local)
1. `pip install -r requirements.txt`; run `streamlit run dashboard.py`.
2. Verify `fetch_official.py` end-to-end against the live PulseLive API; fix
   field/URL assumptions; confirm Moto3 returns flying laps.
3. Confirm auto-load-latest works; then reboot Cloud to ship it.
4. (Optional) bundle more MotoGP-only circuits (Assen/Misano/… from OSM) as
   racing-ordered GeoJSON so Track Map sector-colours them like the bundled 7.
