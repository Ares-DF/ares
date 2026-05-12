package com.ares.atak.plugin

import android.content.Context
import android.content.Intent

/**
 * ARES-ATAK — toolbar tool (skeleton).
 *
 * Declared in `assets/plugin.xml`. Appears in ATAK's toolbar; tapping it
 * broadcasts [AresMapComponent.SHOW_ARES] to open the dropdown pane.
 *
 * Real implementation: `class AresPluginTool(context: Context) :
 * transapps.maps.plugin.tool.Tool` (or `AbstractTool`) — provide `getDescription()`,
 * an icon `Drawable`, and `onActivate(...)` that fires the intent.
 */
class AresPluginTool /* (private val context: Context) : transapps.maps.plugin.tool.Tool */ {

    /* override */ fun getDescription(): String = "ARES — RF propagation & DF"

    /* override */ fun onActivate(context: Context /*, mapView, parent, extras, callback */) {
        context.sendBroadcast(Intent(AresMapComponent.SHOW_ARES))
    }
}
