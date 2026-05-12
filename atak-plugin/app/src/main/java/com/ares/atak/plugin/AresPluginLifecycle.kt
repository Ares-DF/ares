package com.ares.atak.plugin

import android.app.Activity
import android.content.res.Configuration

/**
 * ARES-ATAK — plugin lifecycle entry point (skeleton).
 *
 * Declared in `assets/plugin.xml`. ATAK instantiates this and drives it through
 * the standard lifecycle; we use it to create our [AresMapComponent] which
 * registers receivers / overlays. Real implementation imports
 * `transapps.maps.plugin.lifecycle.Lifecycle` and `com.atakmap.android.maps.MapView`
 * from the tak.gov SDK.
 *
 * TODO(P0): `class AresPluginLifecycle(private val pluginContext: Context) : Lifecycle`
 *           and forward each callback to a list of MapComponents, per the SDK template.
 */
class AresPluginLifecycle /* (private val pluginContext: Context) : transapps.maps.plugin.lifecycle.Lifecycle */ {

    private val mapComponents = mutableListOf<AresMapComponent>()

    /* override */ fun onCreate(activity: Activity /*, mapView: MapView */) {
        // val mc = AresMapComponent()
        // mc.onCreate(pluginContext, activity.intent, mapView)
        // mapComponents += mc
    }

    /* override */ fun onStart() {}
    /* override */ fun onResume() {}
    /* override */ fun onPause() {}
    /* override */ fun onStop() {}
    /* override */ fun onConfigurationChanged(newConfig: Configuration) {}
    /* override */ fun onDestroy() {
        // mapComponents.forEach { it.onDestroy(pluginContext, mapView) }
        mapComponents.clear()
    }
    /* override */ fun onFinish() {}
}
