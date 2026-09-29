"""Step 3 - Prepare terrain for LISFLOOD-FP.

Copernicus GLO-30 DEM (EPSG:4326) -> UTM 42N grid at a chosen resolution ->
reservoir side of the dam masked out (the reservoir is represented by the
breach-outflow hydrograph instead) -> ESRI ASCII grid for LISFLOOD-FP.
"""
import json
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling, transform_bounds
from rasterio.transform import from_origin
from rasterio.features import rasterize
from shapely.geometry import Polygon, mapping
from shapely.ops import transform as shp_transform
from pyproj import Transformer

from config import DATA, BBOX, CRS_MODEL, DAM_CREST, MODEL

SRC_DEM = DATA / "dem" / "N22_00_E070_00.tif"
WALL = 999.0  # elevation (m) given to masked reservoir cells -> no flow


def reservoir_mask_polygon():
    """Polygon covering the reservoir side (SE) of the dam crest."""
    sw, ne = DAM_CREST[0], DAM_CREST[-1]
    ring = list(DAM_CREST) + [(ne[0] + 0.004, ne[1] + 0.0005),
                              (BBOX["east"] + 0.05, ne[1] + 0.0005),
                              (BBOX["east"] + 0.05, BBOX["south"] - 0.05),
                              (sw[0], BBOX["south"] - 0.05)]
    return Polygon(ring)


def prepare(res=30):
    out_dir = MODEL / "terrain"
    out_dir.mkdir(parents=True, exist_ok=True)
    left, bottom, right, top = transform_bounds(
        "EPSG:4326", CRS_MODEL, BBOX["west"], BBOX["south"], BBOX["east"], BBOX["north"])
    left, bottom = np.floor(left / res) * res, np.floor(bottom / res) * res
    ncols = int(np.ceil((right - left) / res))
    nrows = int(np.ceil((top - bottom) / res))
    top = bottom + nrows * res
    transform = from_origin(left, top, res, res)

    dem = np.full((nrows, ncols), np.nan, dtype="float32")
    with rasterio.open(SRC_DEM) as src:
        reproject(rasterio.band(src, 1), dem, dst_transform=transform,
                  dst_crs=CRS_MODEL, resampling=Resampling.bilinear,
                  dst_nodata=np.nan)

    # mask reservoir side
    tf = Transformer.from_crs("EPSG:4326", CRS_MODEL, always_xy=True).transform
    poly_utm = shp_transform(tf, reservoir_mask_polygon())
    mask = rasterize([(mapping(poly_utm), 1)], out_shape=dem.shape,
                     transform=transform, fill=0, dtype="uint8").astype(bool)
    dem[mask] = WALL
    dem = np.where(np.isnan(dem), WALL, dem)

    asc = out_dir / f"dem_{res}m.asc"
    with open(asc, "w") as f:
        f.write(f"ncols {ncols}\nnrows {nrows}\nxllcorner {left}\nyllcorner {bottom}\n"
                f"cellsize {res}\nNODATA_value -9999\n")
        np.savetxt(f, dem, fmt="%.2f")
    profile = dict(driver="GTiff", width=ncols, height=nrows, count=1, dtype="float32",
                   crs=CRS_MODEL, transform=transform, compress="lzw")
    with rasterio.open(out_dir / f"dem_{res}m.tif", "w", **profile) as o:
        o.write(dem, 1)
    np.save(out_dir / f"mask_{res}m.npy", mask)
    meta = dict(res=res, ncols=ncols, nrows=nrows, xll=left, yll=bottom, top=top,
                crs=CRS_MODEL)
    (out_dir / f"meta_{res}m.json").write_text(json.dumps(meta, indent=1))
    valid = dem[~mask]
    print(f"[terrain] {res} m grid {ncols}x{nrows} = {ncols*nrows:,} cells; "
          f"elev {valid.min():.1f}-{valid.max():.1f} m; masked {mask.sum():,} reservoir cells")
    return meta


if __name__ == "__main__":
    import sys
    prepare(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
