const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  onExportGeoJSON: (cb) => ipcRenderer.on('export-geojson', cb),
  onExportPDF:     (cb) => ipcRenderer.on('export-pdf', cb),
  onPurgeCache:    (cb) => ipcRenderer.on('purge-cache', cb),
})
