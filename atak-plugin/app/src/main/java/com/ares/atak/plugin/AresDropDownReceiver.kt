package com.ares.atak.plugin

import android.content.Context
import android.content.Intent
import com.ares.atak.plugin.net.AresApiClient
import com.ares.atak.plugin.net.RadioTemplate
import com.ares.atak.plugin.net.Transmitter
import com.ares.atak.plugin.net.CoverageRequest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * ARES-ATAK — the right-side dropdown pane controller (skeleton).
 *
 * Real impl: `class AresDropDownReceiver(...) : DropDownReceiver(mapView),
 * DropDown.OnStateListener`, inflating `R.layout.ares_main` via
 * `PluginLayoutInflater` and `showDropDown(view, …, this)` on the SHOW_ARES intent.
 *
 * Owns: [AresApiClient] (connection), [SettingsStore] (persisted config),
 * [CoOptManager] (live coverage), [DfManager] (DF / geolocation). Tabs to come:
 * Coverage · RF links · Live coverage · DF/Geolocation · Templates · HF/space-
 * weather · MANET · Settings (see docs/BUILD_PLAN.md §C).
 */
class AresDropDownReceiver(
    private val pluginContext: Context,
    // private val mapView: MapView,
) /* : DropDownReceiver(mapView), DropDown.OnStateListener */ {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val settings = SettingsStore(pluginContext)
    private var api: AresApiClient? = null
    private var coOpt: CoOptManager? = null
    private var df: DfManager? = null
    private var templates: List<RadioTemplate> = emptyList()
    private var selectedTemplate: RadioTemplate? = null

    /* override */ fun onReceive(context: Context, intent: Intent) {
        if (intent.action == AresMapComponent.SHOW_ARES) {
            // val v = PluginLayoutInflater.inflate(pluginContext, R.layout.ares_main, null)
            // wireButtons(v); showDropDown(v, THREE_EIGHTHS_WIDTH, FULL_HEIGHT, HALF_WIDTH, FULL_HEIGHT, this)
            // if a token was persisted, try to resume the session silently:
            if (api == null && !settings.token.isNullOrEmpty()) resumeSession()
        }
    }

    // ── Settings tab → "Log in" ─────────────────────────────────────────────
    fun connect(serverUrl: String, username: String, password: String, allowSelfSigned: Boolean) {
        settings.serverUrl = serverUrl; settings.username = username; settings.allowSelfSigned = allowSelfSigned
        val client = AresApiClient(serverUrl, allowSelfSigned)
        scope.launch {
            try {
                val resp = client.login(username, password)
                settings.token = resp.token
                onConnected(client)
                // status("Connected to $serverUrl")
            } catch (e: Exception) { /* status("Login failed: ${e.message}") */ }
        }
    }

    private fun resumeSession() {
        val client = AresApiClient(settings.serverUrl, settings.allowSelfSigned).apply { setToken(settings.token) }
        scope.launch {
            try { client.serverInfo(); onConnected(client) }   // token still valid
            catch (_: Exception) { settings.token = null }      // expired → require re-login
        }
    }

    private fun onConnected(client: AresApiClient) {
        api = client
        coOpt = CoOptManager(client, settings)
        df = DfManager(client)
        loadTemplates()
    }

    private fun loadTemplates() {
        val client = api ?: return
        scope.launch {
            try { templates = client.listTemplates().templates; selectedTemplate = templates.firstOrNull()
                  /* populate the template spinner */ }
            catch (_: Exception) { /* status("Could not load templates") */ }
        }
    }

    // ── Coverage tab → run coverage from a placed TX (uses the selected template) ──
    fun runCoverageAt(lat: Double, lon: Double, mapItemUid: String?) {
        val client = api ?: return /* status("Connect first") */
        val tmpl = selectedTemplate ?: return /* status("Pick a template first") */
        scope.launch {
            try {
                val req = client.templateCoverageRequest(tmpl.id, lat, lon, null)
                val resp = client.coverage(req)
                val summary = CoverageOverlayRenderer.render(resp, "ARES:${tmpl.id}:${mapItemUid ?: "$lat,$lon"}")
                // status("Coverage: ${summary.covered}/${summary.points} covered")
            } catch (e: Exception) { /* status("Coverage failed: ${e.message}") */ }
        }
    }

    /** Ad-hoc coverage (no template) — used by the "Edit RF" radial-menu sheet. */
    fun runCoverageRaw(tx: Transmitter, radiusKm: Double, minSignalDbm: Double) {
        val client = api ?: return
        scope.launch {
            runCatching { client.coverage(CoverageRequest(transmitter = tx, radiusKm = radiusKm, minSignalDbm = minSignalDbm)) }
                .onSuccess { CoverageOverlayRenderer.render(it, "ARES:adhoc") }
        }
    }

    // ── Co-Opt / DF accessors (the UI tabs drive these) ─────────────────────
    fun coOptManager(): CoOptManager? = coOpt
    fun dfManager(): DfManager? = df
    fun availableTemplates(): List<RadioTemplate> = templates
    fun selectTemplate(id: String) { selectedTemplate = templates.firstOrNull { it.id == id } }

    fun dispose() {
        coOpt?.dispose(); df?.dispose()
        scope.cancel()
        api = null; coOpt = null; df = null
    }
}
