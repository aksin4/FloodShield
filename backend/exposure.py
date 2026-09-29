"""Prepare exposure layers once: buildings, roads, critical facilities,
settlements (OpenStreetMap + Microsoft ML building footprints) and
population (WorldPop 2020 constrained, 100 m) on the model grid."""
import json
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.warp import reproject, Resampling
from shapely.geometry import LineString, Point, Polygon, shape

from config import DATA, CRS_MODEL, BBOX, MODEL

EXP = DATA / "exposure"
EXP.mkdir(exist_ok=True)

FACILITY_TYPES = {"hospital": "Hospital", "clinic": "Clinic", "school": "School",
                  "college": "College", "police": "Police", "fire_station": "Fire station",
                  "townhall": "Government office", "place_of_worship": "Place of worship"}


def build():
    osm = json.loads((DATA / "osm" / "osm.json").read_text())["elements"]
    roads, fac, places, rail, obld = [], [], [], [], []
    for e in osm:
        t = e.get("tags", {})
        g = e.get("geometry")
        if "highway" in t and g and e["type"] == "way":
            roads.append(dict(geometry=LineString([(p["lon"], p["lat"]) for p in g]),
                              name=t.get("name", ""), cls=t["highway"],
                              bridge=t.get("bridge") == "yes"))
        elif t.get("railway") == "rail" and g:
            rail.append(dict(geometry=LineString([(p["lon"], p["lat"]) for p in g]),
                             name=t.get("name", "Railway")))
        elif t.get("amenity") in FACILITY_TYPES:
            if e["type"] == "node":
                pt = Point(e["lon"], e["lat"])
            elif g:
                xs = [p["lon"] for p in g]; ys = [p["lat"] for p in g]
                pt = Point(np.mean(xs), np.mean(ys))
            else:
                continue
            fac.append(dict(geometry=pt, name=t.get("name", "(unnamed)"),
                            type=FACILITY_TYPES[t["amenity"]]))
        elif "place" in t and e["type"] == "node":
            places.append(dict(geometry=Point(e["lon"], e["lat"]),
                               name=t.get("name:en") or t.get("name") or "(unnamed village)",
                               place=t["place"]))
        elif "building" in t and g and len(g) >= 4:
            obld.append(dict(geometry=Polygon([(p["lon"], p["lat"]) for p in g]).centroid))

    to = lambda rows: gpd.GeoDataFrame(rows, crs="EPSG:4326")
    to(roads).to_file(EXP / "roads.geojson")
    to(rail).to_file(EXP / "railways.geojson")
    to(fac).to_file(EXP / "facilities.geojson")
    to(places).to_file(EXP / "places.geojson")

    # Buildings: Microsoft ML footprints (primary) + OSM (fallback) -> centroids
    pts = []
    with open(DATA / "buildings" / "ms_raw.geojsonl") as f:
        for line in f:
            geom = shape(json.loads(line)["geometry"])
            c = geom.centroid
            pts.append((c.x, c.y, geom.area))
    ms = gpd.GeoDataFrame(dict(src="Microsoft"), geometry=gpd.points_from_xy(
        [p[0] for p in pts], [p[1] for p in pts]), crs="EPSG:4326", index=range(len(pts)))
    ms = ms.to_crs(CRS_MODEL)
    np.save(EXP / "buildings_xy.npy", np.c_[ms.geometry.x.values, ms.geometry.y.values])
    print(f"[exposure] roads={len(roads)} rail={len(rail)} facilities={len(fac)} "
          f"places={len(places)} buildings(MS)={len(ms)} buildings(OSM)={len(obld)}")


def population_to_grid(res):
    meta = json.loads((MODEL / "terrain" / f"meta_{res}m.json").read_text())
    from rasterio.transform import from_origin
    tr = from_origin(meta["xll"], meta["top"], res, res)
    out = np.zeros((meta["nrows"], meta["ncols"]), "float32")
    with rasterio.open(DATA / "dem" / "worldpop_2020.tif") as src:
        reproject(rasterio.band(src, 1), out, dst_transform=tr, dst_crs=CRS_MODEL,
                  resampling=Resampling.sum, src_nodata=0, dst_nodata=0)
    np.save(EXP / f"pop_{res}m.npy", out)
    print(f"[exposure] population on {res} m grid: {out.sum():,.0f}")


def crop_worldpop(src_path="/tmp/ind_pop.tif"):
    from rasterio.windows import from_bounds
    with rasterio.open(src_path) as d:
        w = from_bounds(BBOX["west"] - 0.01, BBOX["south"] - 0.01, BBOX["east"] + 0.01,
                        BBOX["north"] + 0.01, d.transform)
        a = d.read(1, window=w)
        a = np.where(a < 0, 0, a).astype("float32")
        p = d.profile
        p.update(width=a.shape[1], height=a.shape[0], transform=d.window_transform(w),
                 compress="lzw", nodata=0, dtype="float32")
        with rasterio.open(DATA / "dem" / "worldpop_2020.tif", "w", **p) as o:
            o.write(a, 1)
    print(f"[exposure] WorldPop crop sum {a.sum():,.0f}")


if __name__ == "__main__":
    import sys
    if "pop" in sys.argv:
        crop_worldpop()
        for r in (30, 60):
            population_to_grid(r)
    else:
        build()
