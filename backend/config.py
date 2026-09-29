"""FloodShield configuration - study area, paths and physical constants."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MODEL = ROOT / "model"
RUNS = MODEL / "runs"
OUTPUTS = ROOT / "outputs"
FRONTEND = ROOT / "frontend"

# LISFLOOD-FP 8.1 executable (compiled from the official Zenodo source)
LISFLOOD_EXE = MODEL / "lisflood" / "lisflood"

# Study area: Machhu-2 dam -> Morbi -> Rann of Kutch (WGS84 lon/lat)
BBOX = dict(west=70.76, south=22.735, east=70.99, north=22.95)
CRS_MODEL = "EPSG:32642"  # UTM zone 42N (metres)

# Dam geometry (OpenStreetMap way 129111381) - crest line SW -> NE
DAM_CREST = [(70.8546, 22.7436), (70.8594, 22.7562), (70.8642, 22.7616),
             (70.8680, 22.7659), (70.8723, 22.7661), (70.8764, 22.7673),
             (70.8793, 22.7667)]
# Machchhu river crosses dam axis here (spillway / river section)
RIVER_CROSSING = (70.8649, 22.7627)

DAM = json.loads((DATA / "dam" / "machhu2.json").read_text())

# Depth thresholds (m) used for flood classes
WET_THRESHOLD = 0.10   # a cell counts as flooded if max depth > 10 cm
DEPTH_CLASSES = [(0.1, 0.5, "Low"), (0.5, 1.5, "Moderate"),
                 (1.5, 3.0, "High"), (3.0, 99, "Very high")]
