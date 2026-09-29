/**
 * FloodShield - Near-real-time flood mapping with Sentinel-1 SAR (Google Earth Engine)
 * PS SIH26161 deliverable 4. Paste into https://code.earthengine.google.com and click Run.
 *
 * Method: before/after change detection on Sentinel-1 VV backscatter (UN-SPIDER recommended
 * practice). A pixel is flagged as flood when the after/before ratio drops sharply, and the
 * result is then masked with permanent water (JRC), steep slopes and high ground (Copernicus DEM).
 * Output: flood polygons exported as SHP / KML to Google Drive, to compare with
 * FloodShield model outputs (outputs/scenarios/<id>/flood_extent_<id>.kml).
 *
 * NOTE: Sentinel-1 revisit here is ~12 days (S1A only in 2024). For the Aug-2024 Machhu release,
 * the nearest passes are 21 Aug (before) and 2 Sep 2024 (after, ~5 days post-peak).
 */

// ---------------- USER SETTINGS ----------------
var aoi = ee.Geometry.Rectangle([70.76, 22.735, 70.99, 22.95]);   // Machhu-2 -> Morbi -> Rann
var BEFORE = ['2024-08-01', '2024-08-22'];
var AFTER  = ['2024-08-26', '2024-09-05'];
var POLARIZATION = 'VV';
var DIFF_THRESHOLD = 1.25;   // after/before ratio (in linear units); tune 1.15 - 1.5
// ------------------------------------------------

Map.centerObject(aoi, 12);

function s1(range) {
  return ee.ImageCollection('COPERNICUS/S1_GRD')
    .filter(ee.Filter.eq('instrumentMode', 'IW'))
    .filter(ee.Filter.listContains('transmitterReceiverPolarisation', POLARIZATION))
    .filter(ee.Filter.eq('resolution_meters', 10))
    .filterBounds(aoi)
    .filterDate(range[0], range[1])
    .select(POLARIZATION);
}
var beforeCol = s1(BEFORE), afterCol = s1(AFTER);
print('Before scenes', beforeCol.aggregate_array('system:time_start').map(function (t) { return ee.Date(t).format('YYYY-MM-dd'); }));
print('After scenes', afterCol.aggregate_array('system:time_start').map(function (t) { return ee.Date(t).format('YYYY-MM-dd'); }));

// Speckle filter (focal mean, 50 m) and convert to linear for the ratio
function prep(img) { return ee.Image(10).pow(img.divide(10)).focal_mean(50, 'circle', 'meters'); }
var before = prep(beforeCol.mosaic()).clip(aoi);
var after  = prep(afterCol.mosaic()).clip(aoi);

var ratio = before.divide(after);                       // water darkens -> ratio > 1
var flood = ratio.gt(DIFF_THRESHOLD);

// Masks: permanent water (JRC >10 months/yr), slope > 5 deg, height above 80 m
var jrc = ee.Image('JRC/GSW1_4/GlobalSurfaceWater').select('seasonality');
var perm = jrc.gte(10).unmask(0);
var dem = ee.ImageCollection('COPERNICUS/DEM/GLO30').select('DEM').filterBounds(aoi).mosaic()
  .setDefaultProjection('EPSG:4326', null, 30);
var slope = ee.Terrain.slope(dem);
flood = flood.updateMask(perm.not()).updateMask(slope.lt(5)).updateMask(dem.lt(80));
// remove speckle islands < 8 connected pixels
flood = flood.updateMask(flood.connectedPixelCount(8, false).gte(8)).selfMask();

var areaKm2 = flood.multiply(ee.Image.pixelArea()).reduceRegion({
  reducer: ee.Reducer.sum(), geometry: aoi, scale: 10, maxPixels: 1e10 }).getNumber(POLARIZATION).divide(1e6);
print('Observed flooded area (km2)', areaKm2);

Map.addLayer(before, {min: 0, max: 0.3}, 'Before (VV)', false);
Map.addLayer(after, {min: 0, max: 0.3}, 'After (VV)', false);
Map.addLayer(perm.selfMask(), {palette: ['#0b3d91']}, 'Permanent water');
Map.addLayer(flood, {palette: ['#22b8cf']}, 'Sentinel-1 flood');

var vectors = flood.reduceToVectors({ geometry: aoi, scale: 20, geometryType: 'polygon',
  eightConnected: false, labelProperty: 'flood', maxPixels: 1e10 });
Export.table.toDrive({ collection: vectors, description: 'FloodShield_S1_flood_SHP', fileFormat: 'SHP' });
Export.table.toDrive({ collection: vectors, description: 'FloodShield_S1_flood_KML', fileFormat: 'KML' });
Export.image.toDrive({ image: flood.toByte(), description: 'FloodShield_S1_flood_raster', region: aoi, scale: 10, maxPixels: 1e10 });
