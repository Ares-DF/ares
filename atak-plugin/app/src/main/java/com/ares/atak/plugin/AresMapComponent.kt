package com.ares.atak.plugin

import android.content.Context
import android.content.Intent

/**
 * ARES-ATAK — map component (skeleton).
 *
 * Real implementation: `class AresMapComponent : DropDownMapComponent()` (from
 * `com.atakmap.android.dropdown.DropDownMapComponent`). In `onCreate` it:
 *   - builds the [AresDropDownReceiver] and registers it for the SHOW_ARES intent,
 *   - registers a radial-menu item ("Edit RF" / "Add LoB from here") on map items,
 *   - subscribes to CoT position reports (drives Co-Opt live coverage + DF),
 *   - creates the map overlay group(s) that coverage layers / DF wedges live in.
 *
 * Kept as a plain class here so the skeleton compiles without the SDK.
 */
class AresMapComponent /* : com.atakmap.android.dropdown.DropDownMapComponent() */ {

    companion object {
        const val SHOW_ARES = "com.ares.atak.plugin.SHOW_ARES"
        const val OVERLAY_GROUP = "ARES"
    }

    private var dropDown: AresDropDownReceiver? = null

    /* override */ fun onCreate(pluginContext: Context, intent: Intent /*, mapView: MapView */) {
        dropDown = AresDropDownReceiver(pluginContext /*, mapView */)
        // registerDropDownReceiver(dropDown, DocumentedIntentFilter(SHOW_ARES))
        // mapView.rootGroup.addGroup(MapGroup ... OVERLAY_GROUP)
        // registerReceiver(mapView, coTPositionListener, ...)
    }

    /* override */ fun onDestroy(pluginContext: Context /*, mapView: MapView */) {
        dropDown?.dispose()
        dropDown = null
    }
}
