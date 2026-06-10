// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2026 Ares

/**
 * Minimal offline .xlsx writer (SpreadsheetML + JSZip — no SheetJS).
 *
 * makeXlsx([{ name, rows }]) → Blob, where `rows` is an array of arrays
 * (first row = header). Numbers become numeric cells; everything else is an
 * inline string, so no sharedStrings part is needed. Enough for Excel,
 * LibreOffice and the i2 Analyst's Notebook import wizard.
 */
import JSZip from 'jszip'

const escXml = (s) => String(s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&apos;')

const colLetter = (i) => {
  let n = i + 1, s = ''
  while (n > 0) { const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = Math.floor((n - 1) / 26) }
  return s
}

const cellXml = (v, ref) => {
  if (v == null || v === '') return ''
  if (typeof v === 'number' && Number.isFinite(v)) return `<c r="${ref}"><v>${v}</v></c>`
  return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${escXml(v)}</t></is></c>`
}

const sheetXml = (rows) => {
  const body = rows.map((row, ri) =>
    `<row r="${ri + 1}">${row.map((v, ci) => cellXml(v, `${colLetter(ci)}${ri + 1}`)).join('')}</row>`
  ).join('')
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    + `<sheetData>${body}</sheetData></worksheet>`
}

// Excel sheet names: ≤31 chars, no []:*?/\ — and must be unique.
const sheetName = (raw, i, used) => {
  let n = String(raw || `Sheet${i + 1}`).replace(/[[\]:*?/\\]/g, ' ').trim().slice(0, 31) || `Sheet${i + 1}`
  let cand = n, k = 2
  while (used.has(cand)) cand = `${n.slice(0, 28)} ${k++}`
  used.add(cand)
  return cand
}

/** Build a .xlsx Blob from [{ name, rows: any[][] }, …]. */
export async function makeXlsx(sheets) {
  const zip = new JSZip()
  const used = new Set()
  const names = sheets.map((s, i) => sheetName(s.name, i, used))

  zip.file('[Content_Types].xml',
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    + '<Default Extension="xml" ContentType="application/xml"/>'
    + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    + sheets.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('')
    + '</Types>')

  zip.file('_rels/.rels',
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    + '</Relationships>')

  zip.file('xl/workbook.xml',
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    + `<sheets>${names.map((n, i) => `<sheet name="${escXml(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('')}</sheets>`
    + '</workbook>')

  zip.file('xl/_rels/workbook.xml.rels',
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    + sheets.map((_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('')
    + '</Relationships>')

  sheets.forEach((s, i) => zip.file(`xl/worksheets/sheet${i + 1}.xml`, sheetXml(s.rows || [])))

  return zip.generateAsync({
    type: 'blob', compression: 'DEFLATE',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
}

/** Trigger a browser download of a Blob. */
export function downloadBlob(blob, filename) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}
