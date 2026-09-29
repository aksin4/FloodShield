"""Step 2 - Download all open input data for the Machhu-2 study area (~110 MB total).

    python download_data.py            # DEM, OSM, Microsoft buildings, WorldPop
Then:
    python terrain.py 60 && python terrain.py 30
    python exposure.py && python exposure.py pop
"""
import csv
import gzip
import io
import json
import math
import requests
from pathlib import Path

from config import DATA, BBOX

B = dict(s=22.68, w=70.75, n=22.95, e=71.0)


def dem():
    out = DATA / "dem" / "N22_00_E070_00.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return print("[dem] exists")
    url = ("https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N22_00_E070_00_DEM/"
           "Copernicus_DSM_COG_10_N22_00_E070_00_DEM.tif")
    out.write_bytes(requests.get(url, timeout=300).content)
    print("[dem] Copernicus GLO-30 tile downloaded")


def osm():
    out = DATA / "osm" / "osm.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    q = (DATA / "osm" / "q.txt").read_text()
    for url in ["https://overpass-api.de/api/interpreter",
                "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
                "https://overpass.kumi.systems/api/interpreter"]:
        try:
            r = requests.post(url, data={"data": q}, timeout=240)
            if r.ok and len(r.content) > 1000:
                out.write_bytes(r.content)
                return print(f"[osm] {len(r.json()['elements'])} elements from {url}")
        except Exception as e:  # noqa
            print("[osm] mirror failed", url, e)
    raise SystemExit("All Overpass mirrors failed - retry later")


def _quadkey(lat, lon, z=9):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    s = math.sin(math.radians(lat))
    y = int((0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n)
    k = ""
    for i in range(z, 0, -1):
        m = 1 << (i - 1)
        k += str((1 if x & m else 0) + (2 if y & m else 0))
    return k


def buildings():
    out = DATA / "buildings" / "ms_raw.geojsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    idx = requests.get("https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv",
                       timeout=120).text
    keys = {_quadkey(la, lo) for la in (B["s"], B["n"]) for lo in (B["w"], B["e"])}
    rows = [r for r in csv.reader(io.StringIO(idx)) if r and r[0] == "India" and r[1] in keys]
    n = 0
    with open(out, "w") as f:
        for r in rows:
            for line in gzip.decompress(requests.get(r[2], timeout=300).content).decode().splitlines():
                c = json.loads(line)["geometry"]["coordinates"][0][0]
                if B["w"] <= c[0] <= B["e"] and B["s"] <= c[1] <= B["n"]:
                    f.write(line + "\n"); n += 1
    print(f"[buildings] {n} Microsoft ML footprints")


def worldpop():
    out = Path("/tmp/ind_pop.tif")
    if out.exists():
        return print("[worldpop] exists")
    url = ("https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/BSGM/IND/"
           "ind_ppp_2020_constrained.tif")
    print("[worldpop] downloading India 2020 constrained (~530 MB) ...")
    with requests.get(url, stream=True, timeout=600) as r, open(out, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    print("[worldpop] done -> run: python exposure.py pop")


if __name__ == "__main__":
    dem(); osm(); buildings(); worldpop()
