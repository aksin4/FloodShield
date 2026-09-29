# FloodShield
Dam-break hydrodynamic inundation and impact assessment system. Built for SIH 2026, PS **SIH26161** (NTRO): "Dam Break Inundation Modelling Using Hydrodynamic Modelling of any River".

Study case: **Machhu-2 Dam, Machchhu River, Morbi (Gujarat)**. This is the site of the 1979 Morbi disaster, which gives us a real historical event to check the model against.

---

## 1. Pipeline

```
Copernicus GLO-30 DEM ──► terrain.py ──► UTM 42N grid (30 m / 60 m), reservoir side masked
Machhu-2 2021 E-A-C curve ─► breach.py ─► breach outflow hydrograph (trapezoidal breach + reservoir mass balance)
                                  │
                                  ▼
                        simulation.py ──► LISFLOOD-FP 8.1 (2D local-inertial shallow-water solver)
                                  │           depth / velocity / arrival time / hazard, every 30 min
                                  ▼
 OSM + MS buildings + WorldPop ─► impact.py ──► buildings, roads, bridges, rail, facilities, settlements, people
                                  │           GeoTIFF + GeoJSON + Shapefile + KML + web PNG frames
                                  ▼
                 run_all.py ──► 4 scenarios + 16-member Latin-hypercube ensemble ──► probability map
                 sph.py ──────► 2D WCSPH near-field breach model (validated: Martin & Moyce 1952)
                 sar_flood.py ► Sentinel-1 observed flood (Aug-2024 release) + gee/ Earth Engine script
                 verification.py ► mass balance, grid convergence, 1979 plausibility check
                                  ▼
                 main.py (FastAPI) ◄──► frontend/ (Leaflet + Chart.js dashboard)
```

## 2. Why these choices

| Decision | Choice | Reason |
|---|---|---|
| Solver | LISFLOOD-FP 8.1 `acceleration` | Open-source 2D shallow-water solver (local-inertial form, Bates et al. 2010). Scriptable, no GUI. Runs on Linux. |
| Breach | Parametric trapezoid (DAMBRK / HEC-RAS method) | This is the industry standard. Breach size and timing come from the Froehlich (2008) regressions. |
| Reservoir | 2021 elevation–capacity table (NHP/CWC survey) | Uses real storage: 92.0 Mm³ at FRL 57.30 m. |
| Terrain | Copernicus GLO-30 | Free, global, 30 m resolution, available from AWS without login. |
| Buildings | Microsoft ML footprints (95,468) | OSM has only ~1,700 buildings in this area, so we use Microsoft's footprints instead. |
| Population | WorldPop 2020 constrained (100 m) | Open data, commonly used for exposure estimates. |

**About the PS naming SPH and Delft3D:** FloodShield is a two-scale framework.
- **Near field (SPH, `sph.py`)**: our own 2D weakly-compressible SPH solver (Wendland C2 kernel, Tait equation of state, δ-SPH, artificial viscosity). It resolves the violent vertical flow right at the breach, where depth-averaged models are least accurate. It is validated against the Martin & Moyce (1952) collapsing-column experiment, with a 2.3% mean front-position error. In a vertical section through the Machhu-2 breach it gives a front speed of 17.2 m/s = 1.41·√(gH), comparable to the ~1.5·√(ga) late-time front speed in the Martin & Moyce data and staying below the Ritter upper bound of 24.5 m/s.
- **Far field (2D shallow-water, LISFLOOD-FP)**: routes the flood 20+ km down the valley. SPH at this scale would take days of compute. Delft3D FM solves the same shallow-water equations. Our `simulation.py` wrapper is solver-agnostic, so Delft3D FM or HEC-RAS 2D can be plugged in later.

## 3. Scenarios (all inputs are assumptions; outputs come from the model)

| ID | Reservoir | Breach width | Formation | Flood inflow | Basis |
|---|---|---|---|---|---|
| S0 Release | FRL 57.30 m | none | – | 3,400 m³/s | Controlled gate release like 28 Aug 2024 (~1.2 lakh cusecs) |
| S1 Moderate | FRL 57.30 m | 140 m | 2.5 h | none | Froehlich 2008 average for this dam |
| S2 Severe | HFL 59.20 m | 400 m | 1.0 h | 8,000 m³/s | Upper end of the regression scatter; overtopping during a flood |
| S3 Extreme | HFL 59.20 m | 1,100 m | 0.75 h | 16,300 m³/s | 1979 analogue (762 m + 365 m of embankment lost; 16,307 m³/s observed) |

Uncertainty ensemble: 16 runs. Breach width 70–350 m, formation time 0.5–3 h, Manning's n 0.04–0.08, reservoir level 55.5–59.2 m.

## 4. How to run (Linux / WSL)

```bash
# 1. Python deps
pip install rasterio geopandas shapely pyproj fastapi uvicorn scipy pillow requests

# 2. LISFLOOD-FP 8.2 source (GPLv3, non-commercial)
wget "https://zenodo.org/records/13121102/files/LISFLOOD-FP-v8.2.zip?download=1" -O lisflood.zip
unzip lisflood.zip && cd LISFLOOD-FP
sed -i 's/set(_NETCDF 1)/set(_NETCDF 0)/' config.default.cmake
sudo apt install libnuma-dev cmake g++          # or use the stub in section 6 if you have no sudo
mkdir build && cd build && cmake .. -DCMAKE_BUILD_TYPE=Release && make -j lisflood
cp lisflood ../../FloodShield/model/lisflood/

# 3. Data (from FloodShield/backend)
python download_data.py                          # DEM, OSM, MS buildings, WorldPop (~650 MB incl. WorldPop)
python terrain.py 60 && python terrain.py 30     # DEM -> model grids
python exposure.py                               # OSM + buildings
python exposure.py pop                           # WorldPop crop -> grids (needs /tmp/ind_pop.tif)

# 4. Simulations
python run_all.py scenarios60 ensemble scenarios # ~1 min per 60 m run, several min per 30 m run

python sph.py validate && python sph.py machhu   # SPH benchmark + breach section (~2 min)
python sar_flood.py                              # Sentinel-1 observed flood layer
python finish.py                                 # S0 at 30 m + verification report

# 5. Dashboard + API
uvicorn main:app --host 0.0.0.0 --port 8000      # open http://localhost:8000
```

On Windows, use WSL2 (Ubuntu). Or compile with the Visual Studio solution that ships with LISFLOOD-FP.

## 5. Three-minute demo script for judges

1. **Scenarios tab, Moderate**: "Froehlich-recommended 140 m breach at FRL. 92 Mm³ is released and 24 km² floods." Press ▶ to play the flood wave.
2. Switch the map layer to **Arrival** and then **Hazard**. Point out the warning time for each settlement in the side panel.
3. **Extreme**: Morbi floods to about 5 m. The 1979 records report 3.7–9.1 m (see Method & data, Verification).
4. **Run simulation**: move the breach width slider and the hydrograph updates instantly. Click Run, and LISFLOOD-FP runs live in about 1–2 min.
5. **Compare**, then **Uncertainty**: the 16-run probability map. "We don't claim one flood line; we show confidence."
6. **SPH near-field**: the benchmark against a lab experiment, then the breach-section particle animation.
7. Tick **Sentinel-1 observed**: the satellite flood of Sep 2024. Download the **KML** and open it in Google Earth.

## 6. API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/dam` | Dam data plus Froehlich recommendations |
| POST | `/api/breach/preview` | Instant breach hydrograph for the given parameters |
| POST | `/api/simulate` | Starts a live LISFLOOD-FP run and returns a job id |
| GET | `/api/job/{id}` | Job status |
| GET | `/api/scenarios`, `/api/scenario/{id}` | Scenario results |
| GET | `/api/uncertainty` | Ensemble probability results |
| GET | `/outputs/scenarios/{id}/…` | GeoTIFF, SHP zip, KML, GeoJSON files |

## 7. Troubleshooting

- **`Could NOT find NUMA`**: install `libnuma-dev`. Without sudo, compile a stub and pass `-DNUMA_ROOT_DIR=/path` to cmake. The stub needs `numa.h` declaring `extern "C" int numa_node_of_cpu(int);` and a `libnuma.a` that returns 0.
- **Overpass API 429 / timeout**: try mirror `https://maps.mail.ru/osm/tools/overpass/api/interpreter`.
- **No water in outputs**: point sources must sit on non-masked cells. Check the `QVAR at point` lines in `model/runs/*/lisflood.log`.
- **Model instability (NaN, huge depths)**: lower `initial_tstep` or raise Manning's n. The acceleration solver becomes unstable below n ≈ 0.02.

## 8. Limits (state these honestly to the judges)

1. Copernicus DEM is a surface model: it includes buildings and trees, and it does not resolve the riverbed below water. Channel depths are approximate.
2. The spillway is assumed to pass the full flood inflow, and breach outflow is added on top. This is conservative.
3. Manning's n is uniform. A land-cover-based n (ESA WorldCover) is the next improvement.
4. The 1979 check is a plausibility check, not a calibration. Morbi, the dam (rebuilt in 1989) and the terrain have all changed since then.
5. "People exposed" means people living in flooded cells. It is not a casualty estimate.

## 9. Roadmap (after SIH submission)

- Land-cover-based Manning's n (ESA WorldCover 10 m).
- Run `gee/sentinel1_flood_morbi.js` on each new Sentinel-1 pass (near-real-time); auto-compare with the model flood extent (Critical Success Index).
- A second dam, to show the workflow is generic: `config.py` only needs the dam JSON, the crest line and a bbox.
- GPU solver (LISFLOOD-FP FV1/DG2 CUDA) for 10 m grids.
