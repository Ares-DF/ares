package com.ares.atak.plugin

import com.ares.atak.plugin.net.CoverageResponse
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * ARES-ATAK — turn an Ares coverage GeoJSON into something ATAK can draw (skeleton).
 *
 * Two strategies (mirrors SOOTHSAYER's options):
 *   1. **vector** — parse the Point FeatureCollection and add graduated
 *      `Polyline`/circle map items to an overlay `MapGroup` ("ARES" group);
 *      restyleable, no server change. (Recommended default.)
 *   2. **raster KMZ** — call `AresApiClient.exportKmz(...)`, drop the .kmz into
 *      `atak/ARES/KMZ/`, and let ATAK import it as an "Image Overlay File";
 *      pixel-for-pixel with the SOOTHSAYER look, sendable to contacts.
 *
 * This skeleton only parses + summarises; the actual MapItem creation needs the
 * `com.atakmap.android.maps.*` SDK classes.
 */
object CoverageOverlayRenderer {

    data class Summary(val points: Int, val covered: Int, val maxSignalDbm: Double?, val minSignalDbm: Double?)

    fun summarize(resp: CoverageResponse): Summary {
        val feats = resp.geojson?.get("features")?.jsonArray ?: return Summary(0, 0, null, null)
        var covered = 0; var maxS: Double? = null; var minS: Double? = null
        for (f in feats) {
            val props = f.jsonObject["properties"]?.jsonObject ?: continue
            val isCov = props["covered"]?.jsonPrimitive?.content?.toBooleanStrictOrNull() ?: true
            if (isCov) covered++
            props["signal_dbm"]?.jsonPrimitive?.content?.toDoubleOrNull()?.let { s ->
                maxS = if (maxS == null || s > maxS!!) s else maxS
                minS = if (minS == null || s < minS!!) s else minS
            }
        }
        return Summary(feats.size, covered, maxS, minS)
    }

    /** TODO(P1): build the ATAK overlay. Pseudocode:
     *
     *   val group = mapView.rootGroup.findMapGroup("ARES") ?: mapView.rootGroup.addGroup("ARES")
     *   group.clearItems()
     *   for (f in features where covered) {
     *       val (lon, lat) = f.coordinates
     *       val c = signalToColor(f.signal_dbm)            // ramp matching the web UI
     *       group.addItem(Marker(GeoPoint(lat, lon)).apply { setColor(c); setMetaBoolean("addToObjList", false) })
     *   }
     *   // or render contour bands as DrawingShapes; or import the KMZ as an ImageOverlay.
     */
    fun render(/* mapView: MapView, */ resp: CoverageResponse, layerName: String): Summary {
        val s = summarize(resp)
        // android.util.Log.i("ARES", "coverage layer '$layerName': ${s.covered}/${s.points} covered, " +
        //     "signal ${s.minSignalDbm}..${s.maxSignalDbm} dBm — TODO render to ATAK overlay")
        return s
    }
}
