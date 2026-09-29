"""Observed flood extent from Sentinel-1 RTC (Microsoft Planetary Computer, open access).

Same method as gee/sentinel1_flood_morbi.js (before/after VV change detection), run in
Python so the dashboard can overlay a satellite-observed layer without a GEE account.
Event: Aug-2024 Gujarat floods, Machhu-2 release. Before = 21 Aug 2024, after = 2 Sep 2024.
"""
import json
import numpy as np
import requests
import rasterio
from rasterio.warp import reproject, Resampling
from scipy import ndimage

from config import BBOX, OUTPUTS, CRS_MODEL
from impact import Grid

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-1-rtc"
RES = 30


def items(date):
    r = requests.post(STAC, json={"collections": ["sentinel-1-rtc"],
                                  "bbox": [BBOX["west"], BBOX["south"], BBOX["east"], BBOX["north"]],
                                  "datetime": f"{date}T00:00:00Z/{date}T23:59:59Z"}, timeout=60).json()
    return r["features"]


def mosaic_vv(date, grid, token):
    out = np.full(grid.shape, np.nan, "float32")
    for f in items(date):
        href = f["assets"]["vv"]["href"] + "?" + token
        with rasterio.open(href) as src:
            tmp = np.full(grid.shape, np.nan, "float32")
            reproject(rasterio.band(src, 1), tmp, dst_transform=grid.transform, dst_crs=CRS_MODEL,
                      resampling=Resampling.average, src_nodata=0, dst_nodata=np.nan)
        out = np.where(np.isnan(out), tmp, out)
    return out


def run(before="2024-08-21", after="2024-09-02", ratio_thr=1.8, after_db_max=-15.0):
    grid = Grid(RES)
    token = requests.get(TOKEN, timeout=30).json()["token"]
    b = mosaic_vv(before, grid, token); a = mosaic_vv(after, grid, token)
    b = ndimage.uniform_filter(np.nan_to_num(b, nan=0), 3); a = ndimage.uniform_filter(np.nan_to_num(a, nan=0), 3)
    a_db = 10 * np.log10(np.maximum(a, 1e-6)); b_db = 10 * np.log10(np.maximum(b, 1e-6))
    ratio = b / np.maximum(a, 1e-6)
    perm = b_db < -18                                   # already water before the event
    flood = (ratio > ratio_thr) & (a_db < after_db_max) & ~perm & ~grid.mask & (grid.dem < 80)
    lab, n = ndimage.label(flood)
    sizes = ndimage.sum(flood, lab, range(1, n + 1))
    flood = np.isin(lab, np.where(sizes >= 6)[0] + 1)
    out = OUTPUTS / "sar"; out.mkdir(parents=True, exist_ok=True)
    grid.save_tif(np.where(flood, 1.0, np.nan), out / "s1_flood_20240902.tif")
    rgba = np.zeros(flood.shape + (4,), np.uint8)
    rgba[flood] = (255, 64, 160, 220)
    rgba[perm & ~grid.mask] = (40, 90, 200, 120)
    bounds = grid.web_png(rgba, out / "s1_flood.png")
    s = dict(before=before, after=after, method="Sentinel-1 RTC VV before/after ratio",
             ratio_thr=ratio_thr, flooded_km2=round(float(flood.sum() * RES * RES / 1e6), 2),
             perm_water_km2=round(float((perm & ~grid.mask).sum() * RES * RES / 1e6), 2),
             png="s1_flood.png", bounds=bounds,
             note="After image is ~5 days after the 28 Aug 2024 release peak; residual flooding only.")
    (out / "summary.json").write_text(json.dumps(s, indent=1))
    print(json.dumps(s))
    return s


if __name__ == "__main__":
    run()
