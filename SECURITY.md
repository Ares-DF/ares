# Security Policy

Ares is an **alpha**, air-gappable RF propagation, geolocation, and passive-observation
platform. We take security issues in the software seriously and appreciate responsible
disclosure.

## Supported versions

Ares ships as a rolling alpha. Only the **latest `master`** receives security fixes; there
are no back-ported maintenance branches yet. Please reproduce on a recent `master` before
reporting.

| Version | Supported |
|---------|-----------|
| `master` (latest) | ✅ |
| Older commits / tagged alphas | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub's **Report a vulnerability** flow:

➡️ **https://github.com/musclemommydf/ares/security/advisories/new**

(Repository → **Security** tab → **Report a vulnerability**.) This opens a private
advisory visible only to you and the maintainers.

When reporting, please include:

- A description of the issue and its impact.
- Steps to reproduce (a minimal proof-of-concept if possible).
- Affected component/path and the commit you tested.
- Your environment (OS, and SDR hardware if relevant).

### What to expect

- **Acknowledgement:** within ~7 days.
- **Assessment & updates:** we'll confirm the issue, agree on severity, and keep you posted
  as we work a fix.
- **Disclosure:** we aim to fix and publish an advisory within ~90 days, coordinated with
  you. We're happy to credit you in the advisory unless you'd rather stay anonymous.

This is a volunteer, best-effort project — timelines are targets, not guarantees.

## Scope

**In scope** — vulnerabilities in the Ares software itself, for example:

- Authentication/authorization bypass in the backend API (see the `ARES_AUTH` model).
- Remote code execution, command/path injection, SSRF, or unsafe deserialization.
- Exposure of secrets, API keys, or stored results to unauthorized callers.
- Crashes or memory-safety issues triggerable from untrusted input (e.g. a crafted IQ
  capture, a malformed OSINT feed, a hostile CoT/ATAK message).
- Injection via imported files (GeoJSON/KML/KMZ/GPX) or untrusted map layers.

**Out of scope / not vulnerabilities:**

- The fact that Ares can **receive** RF, demodulate unencrypted broadcasts, or import OSINT
  is by design — it is a passive observation tool. Concerns about that capability are not
  software vulnerabilities (see *Responsible use* below).
- Issues that require an already-compromised host, physical access to an unlocked machine,
  or a malicious local operator who already has full control.
- Missing hardening on a deployment intentionally bound to a non-loopback address without
  enabling auth — bind to `127.0.0.1` or configure `ARES_AUTH` (see `docs/REMOTE.md`).
- Vulnerabilities in optional, separately-installed third-party tools (GNU Radio, gr-gsm,
  SoapySDR, vocoders, etc.) — report those upstream.
- Reports from automated scanners with no demonstrated, reproducible impact.

## Authorized & lawful use

Ares includes active RF and pentest-tool features (sub-GHz transmit/replay, RFID/NFC
read & emulate). These are provided **solely for lawful, authorized
use** — security research, training, CTFs, and engagements you have explicit written
authorization to conduct. Transmitting on regulated spectrum, intercepting
communications you are not authorized to access, or interfering with networks or devices
may be illegal in your jurisdiction. You are solely responsible for operating Ares within
applicable law (e.g. U.S. CFAA, the Wiretap Act, FCC Part 15/97, and your local
equivalents) and within the scope of any authorization. The passive monitoring features
remain passive and perform no decryption; the active features are disabled by default
(`ARES_AUTHORIZED_ACTIVE=1` enables them) and must not be enabled outside an authorized
scope. See [CONTRIBUTING.md](CONTRIBUTING.md) for the project's scope rules.
