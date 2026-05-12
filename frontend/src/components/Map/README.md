# Map components — 2D (Leaflet) + 3D (Cesium globe)

| File | Role |
|---|---|
| `MapView.jsx` | the existing Leaflet 2D map (default view) |
| `GlobeView.jsx` | **new** — CesiumJS 3D globe (Workstream B). Heavy (~30 MB); import lazily. |
| `ViewModeToggle.jsx` | **new** — small `2D / 3D` toolbar button |
| `../../hooks/useViewMode.js` | **new** — zustand store: `{ mode: '2d'|'3d', view, setMode, toggleMode, setView }` |

## Wiring (done in P1)

`App.jsx` mounts `<GlobeView>` (lazy) instead of `<MapView>` when
`useViewMode().mode === '3d'`, and renders a floating `<ViewModeToggle>` at the
top-right of the map. Requires `npm install` (adds `cesium` + `vite-plugin-cesium`).
For reference, the wiring looks like:

```jsx
import { Suspense, lazy } from 'react'
import { useViewMode } from './hooks/useViewMode'
import ViewModeToggle from './components/Map/ViewModeToggle'
const GlobeView = lazy(() => import('./components/Map/GlobeView'))   // own ~30 MB chunk

// …in the map area, where <MapView .../> is rendered today:
const viewMode = useViewMode((s) => s.mode)
const setView  = useViewMode((s) => s.setView)
const view     = useViewMode((s) => s.view)

{viewMode === '3d'
  ? (
      <Suspense fallback={<div style={{padding:16,color:'#8b949e'}}>Loading 3D globe…</div>}>
        <GlobeView
          center={{ lat: view.lat, lon: view.lon, zoom: view.zoom }}
          onMoveEnd={({ lat, lon }) => setView({ lat, lon })}
        />
      </Suspense>
    )
  : <MapView /* …existing props… */ />
}

// …and put <ViewModeToggle /> in the map toolbar.
```

## P1+ work on `GlobeView`
- Terrain: `CesiumTerrainProvider.fromUrl('/api/v1/packs/terrain/<id>/')` (quantized-mesh, generated from the offline DEM packs — Workstream A).
- Imagery: offline ⇒ OSM pack tile URL; add Sentinel-2 / NAIP / customer `ImageryLayer`s; optional Google Photorealistic 3D Tiles (opt-in key).
- RF layers: coverage GeoJSON/heatmap draped on terrain, LOS rays + obstruction markers, first-Fresnel ellipsoids, 3D antenna lobes, airborne/satellite geometry, DF emitter markers + CAP/CEP ellipses, KMZ import/export.
- Perf: `requestRenderMode`, tuned tile-cache size, a "lite globe" fallback (ellipsoid + 2D imagery, no terrain mesh).

See `docs/BUILD_PLAN.md` §B.
