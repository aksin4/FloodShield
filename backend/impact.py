"""Post-processing + GIS impact assessment of a LISFLOOD-FP run.

Produces: depth/velocity/arrival/hazard rasters (GeoTIFF + web PNG), flood
extent polygons (GeoJSON, Shapefile, KML), time-step animation frames and an
impact summary (buildings, roads, railways, facilities, settlements, people).
"""
import json
import shutil
import zipfile
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling, calculate_default_transform, transform_bounds
from rasterio.features import shapes
from shapely.geometry import shape
from PIL import Image

from config import OUTPUTS, DATA, MODEL, CRS_MODEL, WET_THRESHOLD
from simulation import read_asc

EXP = DATA / "exposure"
DEPTH_BINS = [0.1, 0.5, 1.5, 3.0, 1e9]
DEPTH_LABELS = ["0.1-0.5 m", "0.5-1.5 m", "1.5-3 m", "> 3 m"]
# UK Defra FD2320 flood hazard rating HR = h (v + 0.5) (debris factor omitted)
HAZ_BINS = [0.0, 0.75, 1.25, 2.0, 1e9]
HAZ_LABELS = ["Low (caution)", "Moderate (danger for some)", "Significant (danger for most)",
              "Extreme (danger for all)"]


def _ramp(stops):
    xs = np.array([s[0] for s in stops]); cs = np.array([s[1] for s in stops], float)
    def f(v):
        out = np.zeros(v.shape + (4,), np.uint8)
        for k in range(3):
            out[..., k] = np.interp(v, xs, cs[:, k])
        return out
    return f

DEPTH_RAMP = _ramp([(0.1, (180, 240, 255)), (0.5, (80, 210, 255)), (1.5, (45, 140, 255)),
                    (3.0, (60, 70, 240)), (6.0, (140, 40, 220)), (12.0, (210, 20, 122))])
TIME_RAMP = _ramp([(0, (200, 20, 40)), (1, (240, 110, 40)), (2, (250, 200, 60)),
                   (4, (150, 210, 120)), (8, (70, 150, 200))])
VEL_RAMP = _ramp([(0, (255, 245, 200)), (1, (255, 190, 90)), (2, (240, 110, 50)),
                  (4, (190, 30, 40)), (7, (100, 0, 30))])
HAZ_COLORS = [(250, 220, 90), (245, 150, 50), (225, 60, 40), (130, 0, 40)]


class Grid:
    def __init__(self, res):
        self.meta = json.loads((MODEL / "terrain" / f"meta_{res}m.json").read_text())
        self.res = res
        self.transform = from_origin(self.meta["xll"], self.meta["top"], res, res)
        self.shape = (self.meta["nrows"], self.meta["ncols"])
        self.mask = np.load(MODEL / "terrain" / f"mask_{res}m.npy")
        self.dem = rasterio.open(MODEL / "terrain" / f"dem_{res}m.tif").read(1)

    def rc(self, x, y):
        c = ((x - self.meta["xll"]) // self.res).astype(int)
        r = ((self.meta["top"] - y) // self.res).astype(int)
        ok = (r >= 0) & (r < self.shape[0]) & (c >= 0) & (c < self.shape[1])
        return r, c, ok

    def web_png(self, rgba, path):
        """Warp an RGBA array to Web Mercator and save PNG; return lat/lon bounds."""
        dst_tr, w, h = calculate_default_transform(CRS_MODEL, "EPSG:3857", self.shape[1],
                                                   self.shape[0], *self._bounds())
        out = np.zeros((4, h, w), np.uint8)
        for k in range(4):
            reproject(rgba[..., k], out[k], src_transform=self.transform, src_crs=CRS_MODEL,
                      dst_transform=dst_tr, dst_crs="EPSG:3857", resampling=Resampling.nearest)
        Image.fromarray(np.moveaxis(out, 0, -1), "RGBA").save(path, optimize=True)
        l, b, r, t = rasterio.transform.array_bounds(h, w, dst_tr)
        w_, s_, e_, n_ = transform_bounds("EPSG:3857", "EPSG:4326", r - (r - l), b, r, t)
        return [[s_, w_], [n_, e_]]

    def _bounds(self):
        m = self.meta
        return (m["xll"], m["yll"], m["xll"] + m["ncols"] * self.res, m["top"])

    def save_tif(self, arr, path, nodata=-9999):
        prof = dict(driver="GTiff", width=self.shape[1], height=self.shape[0], count=1,
                    dtype="float32", crs=CRS_MODEL, transform=self.transform,
                    compress="lzw", nodata=nodata)
        with rasterio.open(path, "w", **prof) as o:
            o.write(np.where(np.isnan(arr), nodata, arr).astype("float32"), 1)


def _sample_lines(gdf, grid, depth):
    """Flooded length (km) of each line by sampling every res/2 metres."""
    g = gdf.to_crs(CRS_MODEL)
    step = grid.res / 2
    flooded_km, maxd = [], []
    for geom in g.geometry:
        n = max(2, int(geom.length / step) + 1)
        d = np.linspace(0, geom.length, n)
        pts = [geom.interpolate(v) for v in d]
        x = np.array([p.x for p in pts]); y = np.array([p.y for p in pts])
        r, c, ok = grid.rc(x, y)
        dep = np.zeros(n); dep[ok] = depth[r[ok], c[ok]]
        wet = dep > 0.3  # road considered cut above 30 cm (vehicles unsafe)
        flooded_km.append(wet.mean() * geom.length / 1000.0)
        maxd.append(float(dep.max()))
    return np.array(flooded_km), np.array(maxd)


def analyse(rdir, res, scen_id, label=None):
    grid = Grid(res)
    out = OUTPUTS / "scenarios" / scen_id
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    o = rdir / "out"
    depth, _ = read_asc(o / "res.max")
    vel, _ = read_asc(o / "res.maxVc")
    arr, _ = read_asc(o / "res.inittm")
    depth[grid.mask] = 0
    wet = depth > WET_THRESHOLD
    vel = np.where(wet, np.minimum(vel, 15.0), 0)
    arr = np.where(wet, arr, np.nan)
    haz = np.where(wet, depth * (vel + 0.5), 0)
    cell_km2 = (res * res) / 1e6
    # distance from breach (to report downstream max depth excluding the dam-toe pool)
    from simulation import TO_UTM
    from config import RIVER_CROSSING
    bx, by = TO_UTM(*RIVER_CROSSING)
    yy, xx = np.mgrid[0:grid.shape[0], 0:grid.shape[1]]
    cx = grid.meta["xll"] + (xx + 0.5) * res; cy = grid.meta["top"] - (yy + 0.5) * res
    far = np.hypot(cx - bx, cy - by) > 1000
    info = json.loads((rdir / "info.json").read_text())

    # ---- rasters ----
    grid.save_tif(np.where(wet, depth, np.nan), out / "max_depth.tif")
    grid.save_tif(np.where(wet, vel, np.nan), out / "max_velocity.tif")
    grid.save_tif(arr, out / "arrival_time_h.tif")
    grid.save_tif(np.where(wet, haz, np.nan), out / "hazard_rating.tif")

    layers = {}
    rgba = DEPTH_RAMP(depth); rgba[..., 3] = np.where(wet, 215, 0)
    layers["depth"] = dict(png="depth.png", bounds=grid.web_png(rgba, out / "depth.png"))
    rgba = TIME_RAMP(np.nan_to_num(arr, nan=0)); rgba[..., 3] = np.where(wet, 215, 0)
    layers["arrival"] = dict(png="arrival.png", bounds=grid.web_png(rgba, out / "arrival.png"))
    rgba = VEL_RAMP(vel); rgba[..., 3] = np.where(wet, 215, 0)
    layers["velocity"] = dict(png="velocity.png", bounds=grid.web_png(rgba, out / "velocity.png"))
    hcls = np.digitize(haz, HAZ_BINS[1:-1])
    rgba = np.zeros(depth.shape + (4,), np.uint8)
    for k, col in enumerate(HAZ_COLORS):
        rgba[hcls == k, :3] = col
    rgba[..., 3] = np.where(wet, 220, 0)
    layers["hazard"] = dict(png="hazard.png", bounds=grid.web_png(rgba, out / "hazard.png"))

    # ---- animation frames (water depth every saveint) ----
    frames = []
    fdir = out / "frames"; fdir.mkdir()
    wd_files = sorted(o.glob("res-*.wd"))
    saveint = info["scenario"].get("saveint_s", 1800)
    for k, fwd in enumerate(wd_files):
        d, _ = read_asc(fwd); d[grid.mask] = 0
        rgba = DEPTH_RAMP(d); rgba[..., 3] = np.where(d > WET_THRESHOLD, 215, 0)
        b = grid.web_png(rgba, fdir / f"f{k:03d}.png")
        frames.append(dict(png=f"frames/f{k:03d}.png", t_h=round(k * saveint / 3600, 2),
                           area_km2=round(float((d > WET_THRESHOLD).sum() * cell_km2), 2)))
    layers["frames_bounds"] = b if wd_files else None

    # ---- flood extent vectors (depth classes) -> GeoJSON / SHP / KML ----
    cls = np.digitize(depth, DEPTH_BINS) * wet  # 1..4
    polys = []
    for geom, v in shapes(cls.astype("int16"), mask=wet, transform=grid.transform):
        polys.append(dict(geometry=shape(geom), depth_cls=DEPTH_LABELS[int(v) - 1],
                          cls=int(v)))
    gdf = gpd.GeoDataFrame(polys, crs=CRS_MODEL).dissolve(by="cls", as_index=False)
    gdf["geometry"] = gdf.geometry.simplify(res * 0.4)
    gdf["area_km2"] = (gdf.area / 1e6).round(3)
    gdf["scenario"] = scen_id
    g4326 = gdf.to_crs("EPSG:4326")
    g4326.to_file(out / "flood_extent.geojson", driver="GeoJSON")
    shp_dir = out / "shp"; shp_dir.mkdir()
    g4326.to_file(shp_dir / f"flood_extent_{scen_id}.shp")
    with zipfile.ZipFile(out / f"flood_extent_{scen_id}_shp.zip", "w") as z:
        for p in shp_dir.iterdir():
            z.write(p, p.name)
    kml = g4326[["depth_cls", "area_km2", "geometry"]].rename(columns={"depth_cls": "Name"})
    kml.to_file(out / f"flood_extent_{scen_id}.kml", driver="KML")

    # ---- impacts ----
    bxy = np.load(EXP / "buildings_xy.npy")
    r, c, ok = grid.rc(bxy[:, 0], bxy[:, 1])
    bdep = np.zeros(len(bxy)); bdep[ok] = depth[r[ok], c[ok]]
    bcls = np.digitize(bdep, DEPTH_BINS)
    buildings = {lab: int((bcls == k + 1).sum()) for k, lab in enumerate(DEPTH_LABELS)}
    buildings["total"] = int((bdep > WET_THRESHOLD).sum())
    buildings["in_study_area"] = int(len(bxy))

    roads = gpd.read_file(EXP / "roads.geojson")
    rkm, rmax = _sample_lines(roads, grid, depth)
    roads["flooded_km"] = rkm; roads["max_depth"] = rmax
    major = roads["cls"].isin(["motorway", "trunk", "primary", "secondary"])
    road_stats = dict(total_km=round(float(rkm.sum()), 1),
                      major_km=round(float(rkm[major.values].sum()), 1),
                      segments_cut=int((rmax > 0.3).sum()),
                      bridges_affected=int(((rmax > 0.3) & roads["bridge"].values).sum()))
    cut_named = (roads[(roads.max_depth > 0.3) & (roads.name != "")]
                 .groupby("name").agg(km=("flooded_km", "sum"), depth=("max_depth", "max"))
                 .sort_values("km", ascending=False).head(8))
    road_stats["named"] = [dict(name=n, km=round(float(v.km), 2), max_depth=round(float(v.depth), 1))
                           for n, v in cut_named.iterrows()]
    cut = roads[roads.max_depth > 0.3][["name", "cls", "max_depth", "flooded_km", "geometry"]]
    cut.to_file(out / "roads_cut.geojson", driver="GeoJSON")

    rail = gpd.read_file(EXP / "railways.geojson")
    rlkm, _ = _sample_lines(rail, grid, depth) if len(rail) else (np.zeros(0), None)

    def point_stats(gdf, radius_cells=0):
        g = gdf.to_crs(CRS_MODEL)
        r, c, ok = grid.rc(g.geometry.x.values, g.geometry.y.values)
        dd, tt = [], []
        for i in range(len(g)):
            if not ok[i]:
                dd.append(0.0); tt.append(None); continue
            sl = (slice(max(r[i] - radius_cells, 0), r[i] + radius_cells + 1),
                  slice(max(c[i] - radius_cells, 0), c[i] + radius_cells + 1))
            dd.append(float(depth[sl].max()))
            a = arr[sl]
            tt.append(None if np.all(np.isnan(a)) else round(float(np.nanmin(a)), 2))
        return np.array(dd), tt

    fac = gpd.read_file(EXP / "facilities.geojson")
    fd, ft = point_stats(fac)
    fac_hit = [dict(name=fac.name[i], type=fac.type[i], depth=round(fd[i], 2), arrival_h=ft[i],
                    lat=float(fac.geometry.y[i]), lon=float(fac.geometry.x[i]))
               for i in np.argsort(-fd) if fd[i] > WET_THRESHOLD]

    places = gpd.read_file(EXP / "places.geojson")
    pd_, pt_ = point_stats(places, radius_cells=max(1, int(300 / res)))
    place_hit = [dict(name=places.name[i], place=places.place[i], depth=round(pd_[i], 2),
                      arrival_h=pt_[i], lat=float(places.geometry.y[i]),
                      lon=float(places.geometry.x[i]))
                 for i in np.argsort([t if t is not None else 99 for t in pt_]) if pd_[i] > WET_THRESHOLD]

    pop_path = EXP / f"pop_{res}m.npy"
    people = None
    if pop_path.exists():
        pop = np.load(pop_path)
        people = dict(total=int(pop[wet].sum()),
                      **{lab: int(pop[(np.digitize(depth, DEPTH_BINS) == k + 1) & wet].sum())
                         for k, lab in enumerate(DEPTH_LABELS)},
                      hazard_significant_or_extreme=int(pop[wet & (haz >= 1.25)].sum()))

    area_by_cls = {lab: round(float(((np.digitize(depth, DEPTH_BINS) == k + 1) & wet).sum() * cell_km2), 2)
                   for k, lab in enumerate(DEPTH_LABELS)}
    haz_area = {lab: round(float((wet & (hcls == k)).sum() * cell_km2), 2)
                for k, lab in enumerate(HAZ_LABELS)}
    arr_valid = arr[~np.isnan(arr)]
    summary = dict(
        id=scen_id, label=label or scen_id, res=res, model=info,
        flood=dict(area_km2=round(float(wet.sum() * cell_km2), 2),
                   max_depth_m=round(float(depth[wet].max()), 2) if wet.any() else 0,
                   max_depth_ds_m=round(float(depth[wet & far].max()), 2) if (wet & far).any() else 0,
                   p90_depth_m=round(float(np.percentile(depth[wet], 90)), 2) if wet.any() else 0,
                   mean_depth_m=round(float(depth[wet].mean()), 2) if wet.any() else 0,
                   max_velocity_ms=round(float(vel.max()), 2),
                   volume_mcm=round(float(depth[wet].sum() * res * res / 1e6), 2),
                   area_by_depth=area_by_cls, area_by_hazard=haz_area,
                   arrival_p50_h=round(float(np.median(arr_valid)), 2) if arr_valid.size else None),
        buildings=buildings, roads=road_stats,
        railway_km=round(float(rlkm.sum()), 2) if len(rlkm) else 0.0,
        facilities=fac_hit, places=place_hit, people=people,
        layers=layers, frames=frames,
        downloads=dict(geojson="flood_extent.geojson", shp=f"flood_extent_{scen_id}_shp.zip",
                       kml=f"flood_extent_{scen_id}.kml", depth_tif="max_depth.tif",
                       hazard_tif="hazard_rating.tif", arrival_tif="arrival_time_h.tif"))
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    return summary


if __name__ == "__main__":
    s = analyse(MODEL / "runs" / "test_60m", 60, "test")
    print(json.dumps({k: v for k, v in s.items() if k not in ("layers", "frames", "model")},
                     indent=1)[:3000])
