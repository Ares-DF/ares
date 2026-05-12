package com.ares.atak.plugin

import com.ares.atak.plugin.net.AresApiClient
import com.ares.atak.plugin.net.GeoFixOptions
import com.ares.atak.plugin.net.GeoFixRequest
import com.ares.atak.plugin.net.GeoFixResponse
import com.ares.atak.plugin.net.GeoLineOfBearing
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * ARES-ATAK — DF / geolocation mode (skeleton). The Ares-exclusive feature
 * SOOTHSAYER has no answer to.
 *
 * Flow:
 *   1. operator adds Lines-of-Bearing (radial-menu "Add LoB from here" on the
 *      self / a sensor marker): azimuth, RSSI, frequency, antenna, observer
 *      height, confidence, device id, time;
 *   2. (optional) each bearing is terrain-capped by calling
 *      `POST /api/v1/lob/range_estimate` per LoB → `estimatedDistanceM`;
 *   3. all LoBs are POSTed to `POST /api/v1/geolocate/fix` → Cut/Fix grouping,
 *      pairwise intersections, confidence-weighted centroid, CEP/CAP ellipse,
 *      and a GeoJSON FeatureCollection (bearing wedges, ellipses, suspected
 *      emitters);
 *   4. results are drawn on the ATAK map and a "suspected emitter" CoT marker is
 *      published to the team (so everyone sees it), with the option to feed the
 *      fix into a `/simulate/coverage` run ("if that's their repeater, who can
 *      it hear?").
 *
 * The CoT publish + map drawing need the `com.atakmap.android.maps.*` /
 * `com.atakmap.comms.*` SDK classes; modelled here, wired in P3.
 */
class DfManager(private val api: AresApiClient) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val lobs = mutableListOf<GeoLineOfBearing>()
    private var rxHpbwDeg: Double? = 30.0   // receiver -3 dB beamwidth → widens the CEP

    fun setReceiverBeamwidth(deg: Double?) { rxHpbwDeg = deg }

    fun addLoB(lob: GeoLineOfBearing) { lobs += lob }
    fun clear() { lobs.clear() /* TODO: clear DF overlay group */ }
    fun count() = lobs.size

    /** Solve fixes from the current LoB set. `onResult` gets the parsed response;
     *  `onError` gets a message. Draws to the map + publishes CoT in P3. */
    fun solve(onResult: (GeoFixResponse) -> Unit, onError: (String) -> Unit) {
        if (lobs.isEmpty()) { onError("no LoBs added"); return }
        scope.launch {
            try {
                val resp = api.geolocateFix(GeoFixRequest(lobs.toList(), GeoFixOptions(rxHpbwDeg = rxHpbwDeg)))
                // TODO(P3): render resp.geojson (wedges/ellipses/emitter points) into the "ARES-DF" map group;
                //           for each "suspected_emitter" feature, publish a CoT marker (type a-h-G... / a custom);
                //           offer "model this emitter's coverage" → AresApiClient.coverage(...).
                onResult(resp)
            } catch (e: Exception) { onError(e.message ?: e.toString()) }
        }
    }

    /** Optional: terrain-aware bearing caps via /lob/range_estimate before solving. */
    fun refineWithTerrain(onDone: () -> Unit) {
        // TODO(P3): for each LoB, POST /api/v1/lob/range_estimate {observer..., azimuth, freq, tx_power, observed_rssi}
        //           and set estimatedDistanceM from the response; then call solve(...).
        onDone()
    }

    fun dispose() = scope.coroutineContext[Job]?.cancel()
}
