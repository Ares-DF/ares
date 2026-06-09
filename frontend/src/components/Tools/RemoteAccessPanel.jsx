// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2026 Ares

/**
 * RemoteAccessControls — step-by-step wizard for letting a phone / laptop drive
 * this Ares over the network. Embedded in the ATAK / Server console.
 *
 * Talks to the Tauri shell (window.aresDesktop, exposed by preload):
 *   • getRemote() → { enabled, hasPassword, port, lanIps, urls }
 *   • setRemote({enabled, password}) → relaunches the backend bound to 0.0.0.0
 *     with auth + the password (or back to loopback), returns fresh status.
 *
 * Steps:
 *   0  Intro       — explain what this does, "Start setup".
 *   1  Password    — set / change the admin password, "Continue".
 *   2  Applying    — spinner while the backend restarts.
 *   3  Connect     — QR + URL + per-interface picker; from here you can change
 *                    the password or turn it off again.
 *
 * If remote is already on at mount we jump straight to step 3 (skip the intro).
 */
import { useEffect, useMemo, useState } from 'react'
import { Wifi, Copy, Check, Loader2, ShieldCheck, ShieldOff, ChevronRight, ChevronLeft } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'

const desk = (typeof window !== 'undefined') ? window.aresDesktop : null

const MUTED = '#8b949e'
const TEXT = '#c9d1d9'
const BORDER = '#30363d'
const ACCENT = '#1f6feb'
const OK = '#06d6a0'
const RED = '#f85149'

const label = { display: 'block', fontSize: 12, color: MUTED, margin: '14px 0 4px' }
const input = {
  width: '100%', background: '#161b22', border: `1px solid ${BORDER}`, borderRadius: 8,
  color: '#e6edf3', padding: '11px 12px', fontSize: 16, outline: 'none', boxSizing: 'border-box',
}
const primary = {
  padding: '10px 14px', fontSize: 14, fontWeight: 700, border: 'none', borderRadius: 8,
  cursor: 'pointer', color: '#fff', background: ACCENT, display: 'inline-flex', alignItems: 'center', gap: 6,
}
const secondary = {
  padding: '10px 14px', fontSize: 14, fontWeight: 600, borderRadius: 8, cursor: 'pointer',
  color: TEXT, background: '#21262d', border: `1px solid ${BORDER}`,
}

export default function RemoteAccessControls() {
  const [status, setStatus] = useState(null)
  const [step, setStep] = useState(0)
  const [password, setPassword] = useState('')
  const [sel, setSel] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!desk) return
    // getRemote() can throw *synchronously* (e.g. the Tauri shim dereferences
    // window.__TAURI__ before it's injected) — Promise.resolve().then keeps that
    // throw on the rejection path instead of escaping the effect and blanking the app.
    Promise.resolve()
      .then(() => desk.getRemote())
      .then((s) => { setStatus(s); setStep(s.enabled ? 3 : 0) })
      .catch((e) => setErr(String(e?.message || e)))
  }, [])

  const enabled = !!status?.enabled
  const urls = status?.urls || []
  const url = urls[sel] || urls[0] || ''
  const copy = () => { try { navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* noop */ } }

  const apply = async (nextEnabled) => {
    setErr('')
    if (nextEnabled && !password && !status?.hasPassword) {
      setErr('Set a password first — it protects the connection.'); return
    }
    setBusy(true); setStep(2)
    try {
      const s = await Promise.resolve().then(() => desk.setRemote({ enabled: nextEnabled, password }))
      setStatus(s); setPassword(''); setSel(0)
      setStep(s.enabled ? 3 : 0)
    } catch (e) {
      setErr(String(e?.message || e))
      setStep(nextEnabled ? 1 : 3)
    }
    setBusy(false)
  }

  if (!desk) {
    return (
      <div style={{ fontSize: 12.5, color: TEXT, lineHeight: 1.5 }}>
        Remote access is configured from the <b>Ares desktop app</b> (it manages the backend).
        You’re seeing this in a browser — which means you’re already connected remotely. 🎉
      </div>
    )
  }

  // Status pill — visible on every step so the operator always knows where they stand.
  const pill = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px',
                  background: '#161b22', border: `1px solid ${enabled ? 'rgba(6,214,160,0.4)' : '#21262d'}`,
                  borderRadius: 8, marginBottom: 12 }}>
      {enabled ? <ShieldCheck size={18} color={OK} /> : <ShieldOff size={18} color={MUTED} />}
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{enabled ? 'Remote access is ON' : 'Remote access is OFF'}</div>
        <div style={{ fontSize: 11, color: '#6e7681' }}>{enabled ? 'Reachable from your network' : 'Loopback only (this computer)'}</div>
      </div>
      <Stepper step={step} />
    </div>
  )

  return (
    <div>
      {pill}
      {err && <div style={{ color: RED, fontSize: 12, marginBottom: 10 }}>⚠ {err}</div>}

      {step === 0 && <StepIntro onNext={() => setStep(1)} status={status} />}
      {step === 1 && <StepPassword
        password={password} setPassword={setPassword} hasPassword={!!status?.hasPassword}
        onBack={enabled ? () => setStep(3) : null}
        onNext={() => apply(true)} busy={busy} />}
      {step === 2 && <StepApplying />}
      {step === 3 && enabled && <StepConnected
        url={url} urls={urls} sel={sel} setSel={setSel}
        copied={copied} onCopy={copy}
        onChangePassword={() => setStep(1)}
        onDisable={() => apply(false)} busy={busy} />}

      <style>{'@keyframes ares-spin{to{transform:rotate(360deg)}}'}</style>
    </div>
  )
}

function Stepper({ step }) {
  // 4 dots, current highlighted. Step 2 (Applying) is transient; we show 0/1/3 as the three
  // user-visible phases (intro · set password · connected). Step 2 maps onto 1.
  const visual = step === 2 ? 1 : step === 3 ? 2 : step
  return (
    <div style={{ display: 'flex', gap: 5 }}>
      {[0, 1, 2].map(i => (
        <div key={i} style={{ width: 6, height: 6, borderRadius: 3,
                              background: i === visual ? ACCENT : '#30363d' }} />
      ))}
    </div>
  )
}

function StepIntro({ onNext, status }) {
  return (
    <div>
      <div style={{ fontSize: 13, color: TEXT, lineHeight: 1.55, marginBottom: 10 }}>
        Let a phone or another laptop drive this Ares over the network. The backend will
        be exposed on every network interface with password-protected sign-in; this desktop
        stays signed in automatically.
      </div>
      <ul style={{ fontSize: 12, color: MUTED, lineHeight: 1.7, margin: '0 0 14px 18px', padding: 0 }}>
        <li>You’ll set an <b>admin</b> password (the username is always <code>admin</code>).</li>
        <li>The backend restarts bound to all interfaces — a live capture will blip briefly.</li>
        <li>You’ll get a QR code and URL to open on the other device.</li>
        {status && status.lanIps && status.lanIps.length > 0 && (
          <li>Detected LAN address{status.lanIps.length > 1 ? 'es' : ''}: <b>{status.lanIps.join(', ')}</b>.</li>
        )}
      </ul>
      <button style={primary} onClick={onNext}>
        <Wifi size={15} /> Start setup <ChevronRight size={15} />
      </button>
    </div>
  )
}

function StepPassword({ password, setPassword, hasPassword, onBack, onNext, busy }) {
  const tooShort = password.length > 0 && password.length < 6
  const canContinue = (hasPassword && password.length === 0) || password.length >= 6
  return (
    <div>
      <div style={{ fontSize: 13, color: TEXT, lineHeight: 1.55 }}>
        {hasPassword ? 'You can keep the existing password or set a new one.' :
                       'Pick a password — at least 6 characters. Username on the phone is admin.'}
      </div>
      <label style={label}>{hasPassword ? 'New password (leave blank to keep current)' : 'Password'}</label>
      <input style={input} type="password" value={password} onChange={(e) => setPassword(e.target.value)}
             placeholder="admin password" autoComplete="new-password"
             onKeyDown={e => { if (e.key === 'Enter' && canContinue && !busy) onNext() }} />
      {tooShort && <div style={{ color: RED, fontSize: 11, marginTop: 4 }}>At least 6 characters.</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'space-between' }}>
        {onBack
          ? <button style={secondary} onClick={onBack}><ChevronLeft size={14} /> Cancel</button>
          : <span />}
        <button style={{ ...primary, opacity: !canContinue || busy ? 0.55 : 1, cursor: !canContinue || busy ? 'not-allowed' : 'pointer' }}
                onClick={() => canContinue && !busy && onNext()} disabled={!canContinue || busy}>
          {busy ? <Loader2 size={15} style={{ animation: 'ares-spin 1s linear infinite' }} /> : <ChevronRight size={15} />}
          {busy ? 'Applying…' : (hasPassword ? 'Update' : 'Continue')}
        </button>
      </div>
    </div>
  )
}

function StepApplying() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 0' }}>
      <Loader2 size={18} color={ACCENT} style={{ animation: 'ares-spin 1s linear infinite' }} />
      <div>
        <div style={{ fontSize: 13, color: TEXT }}>Restarting the backend…</div>
        <div style={{ fontSize: 11, color: MUTED }}>A live capture will blip for a few seconds.</div>
      </div>
    </div>
  )
}

function StepConnected({ url, urls, sel, setSel, copied, onCopy, onChangePassword, onDisable, busy }) {
  return (
    <div>
      <div style={{ fontSize: 13, color: TEXT, marginBottom: 10 }}>
        Open this on the other device (same network), then sign in as <b>admin</b>:
      </div>
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        {url && (
          <div style={{ background: '#fff', padding: 8, borderRadius: 8 }}>
            <QRCodeSVG value={url} size={132} includeMargin={false} />
          </div>
        )}
        <div style={{ flex: 1, minWidth: 200 }}>
          {urls.length > 1 && (
            <select value={sel} onChange={(e) => setSel(Number(e.target.value))}
                    style={{ ...input, padding: '8px 10px', fontSize: 13, marginBottom: 8 }}>
              {urls.map((u, i) => <option key={u} value={i}>{u}</option>)}
            </select>
          )}
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <code style={{ flex: 1, fontSize: 13, color: '#58a6ff', wordBreak: 'break-all',
                           background: '#161b22', border: `1px solid ${BORDER}`, borderRadius: 6, padding: '6px 8px' }}>{url}</code>
            <button className="btn btn-ghost" style={{ padding: '6px 8px' }} onClick={onCopy} title="Copy">
              {copied ? <Check size={14} color={OK} /> : <Copy size={14} />}
            </button>
          </div>
          <div style={{ fontSize: 11, color: '#6e7681', marginTop: 8 }}>
            Scan the QR or type the address into the phone’s browser. Username <b>admin</b>.
          </div>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 18, borderTop: `1px solid #21262d`, paddingTop: 12 }}>
        <button style={secondary} disabled={busy} onClick={onChangePassword}>Change password</button>
        <button style={{ ...secondary, color: '#fca5a5', borderColor: '#7f1d1d', background: '#3d1a1a' }}
                disabled={busy} onClick={onDisable}>Turn off</button>
      </div>
    </div>
  )
}
