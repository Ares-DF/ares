#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# install-signalhound.sh — stage the SignalHound vendor SDK and build the
# community SoapySignalHound bridge, in one shot. The same logic also runs
# inside ./install.sh's section 4a^^, but is broken out here so it can be
# invoked standalone whenever the SDK is refreshed or a SignalHound radio is
# added after the rest of Ares is already installed.
#
# Usage:
#   sudo ARES_SIGNALHOUND_SDK=/path/to/extracted/sdk ./scripts/install-signalhound.sh
# or:
#   sudo ./scripts/install-signalhound.sh /path/to/extracted/sdk
#
# The path may point at either the zip's extraction parent dir or the
# signal_hound_sdk/ dir itself — both are auto-detected.
#
# What it does (works on apt + dnf systems):
#   1. Picks the per-arch (linux_x64 / aarch64) and per-distro (Red Hat 8 /
#      Ubuntu 18.04 / …) lib folder appropriate for THIS host.
#   2. Copies the matching libbb_api.so.X.Y.Z + libsm_api.so.X.Y.Z + the
#      bundled libftd2xx.so + all the headers into /usr/local/{lib,include}.
#   3. Drops the vendor's own sh_usb.rules into /etc/udev/rules.d/.
#   4. Runs ldconfig so the SONAME symlinks materialize from the embedded
#      sonames, then creates the unversioned dev-link names (libbb_api.so →
#      libbb_api.so.5) that -lbb_api expects.
#   5. Clones + builds altaf-4-1/SoapySignalHound into ~/.cache/ares-sdr/ and
#      installs the module into /usr/local so SoapySDR sees the device.
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

SDK_INPUT="${1:-${ARES_SIGNALHOUND_SDK:-}}"
[ -n "$SDK_INPUT" ] || { echo "usage: sudo ARES_SIGNALHOUND_SDK=<sdk-dir> $0   (or pass the dir as arg 1)"; exit 1; }
[ -d "$SDK_INPUT" ] || { echo "[!] not a directory: $SDK_INPUT"; exit 1; }
[ "$(id -u)" = "0" ] || { echo "[!] this script writes to /usr/local and /etc/udev — run with sudo."; exit 1; }

log()  { echo "[*] $*"; }
ok()   { echo "[✓] $*"; }
warn() { echo "[!] $*"; }

# ── 1. Locate the SDK root that contains device_apis/. ───────────────────────
SH_ROOT=""
for cand in "$SDK_INPUT" "$SDK_INPUT/signal_hound_sdk"; do
    [ -d "$cand/device_apis" ] && SH_ROOT="$cand" && break
done
if [ -z "$SH_ROOT" ]; then
    _found="$(find "$SDK_INPUT" -maxdepth 3 -type d -name device_apis 2>/dev/null | head -1)"
    [ -n "$_found" ] && SH_ROOT="$(dirname "$_found")"
fi
[ -n "$SH_ROOT" ] && [ -d "$SH_ROOT/device_apis" ] || { warn "couldn't locate device_apis/ under $SDK_INPUT"; exit 1; }
log "SDK root: $SH_ROOT"

# ── 2. Pick the right lib folder for this host. ──────────────────────────────
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  LIB_ARCH_DIR="linux_x64" ;;
    aarch64) LIB_ARCH_DIR="aarch64"   ;;
    *) warn "no SDK build for arch $ARCH"; exit 1 ;;
esac
OS_ID=""; ID_LIKE=""
[ -r /etc/os-release ] && { . /etc/os-release; OS_ID="${ID:-}"; }
case "$OS_ID/${ID_LIKE:-}" in
    rhel/*|rocky/*|almalinux/*|fedora/*|centos/*|*/*rhel*|*/*fedora*|*/*centos*)
        DISTRO_PREF=("Red Hat 8" "Red Hat 7" "CentOS 7" "Ubuntu 18.04" "Ubuntu 14.04") ;;
    *)
        DISTRO_PREF=("Ubuntu 18.04" "Red Hat 8" "CentOS 7" "Red Hat 7" "Ubuntu 14.04") ;;
esac
log "Host arch=$ARCH  distro-pref=${DISTRO_PREF[*]}"

# ── 3. Stage libs + headers + udev rule for each device family. ──────────────
STAGED=()
UDEV_FROM=""
for fam in bb_series sm_series; do
    fam_path="$SH_ROOT/device_apis/$fam"
    [ -d "$fam_path" ] || continue
    src_dir=""
    if [ "$LIB_ARCH_DIR" = "linux_x64" ]; then
        for d in "${DISTRO_PREF[@]}"; do
            if [ -d "$fam_path/lib/linux_x64/$d" ]; then src_dir="$fam_path/lib/linux_x64/$d"; break; fi
        done
    elif [ -d "$fam_path/lib/$LIB_ARCH_DIR" ]; then
        src_dir="$fam_path/lib/$LIB_ARCH_DIR"
    fi
    if [ -z "$src_dir" ]; then
        warn "$fam: no SDK build for arch=$ARCH on this distro — skipping."
        continue
    fi
    log "  $fam ← $src_dir"
    for so in "$src_dir"/*.so*; do
        [ -f "$so" ] || continue
        base="$(basename "$so")"
        install -m 755 "$so" "/usr/local/lib/$base"
        STAGED+=("$base")
    done
    if [ -d "$fam_path/include" ]; then
        for hdr in "$fam_path/include"/*.h; do
            [ -f "$hdr" ] || continue
            install -m 644 "$hdr" "/usr/local/include/$(basename "$hdr")"
        done
    fi
    if [ -z "$UDEV_FROM" ]; then
        if   [ -f "$src_dir/sh_usb.rules" ];    then UDEV_FROM="$src_dir/sh_usb.rules"
        elif [ -f "$src_dir/../sh_usb.rules" ]; then UDEV_FROM="$src_dir/../sh_usb.rules"
        fi
    fi
done
[ ${#STAGED[@]} -gt 0 ] || { warn "nothing was staged — check the SDK layout."; exit 1; }
ok "Staged ${#STAGED[@]} file(s) into /usr/local."

# ── 4. ldconfig + unversioned SONAME symlinks. ───────────────────────────────
ldconfig -n /usr/local/lib
ldconfig
for stem in libbb_api libsm_api; do
    soname="$(ls -1 /usr/local/lib/${stem}.so.* 2>/dev/null | grep -E "/${stem}\.so\.[0-9]+$" | sort -V | tail -1)"
    if [ -n "$soname" ]; then
        ln -sf "$(basename "$soname")" "/usr/local/lib/${stem}.so"
        ok "/usr/local/lib/${stem}.so → $(basename "$soname")"
    fi
done

# ── 5. Vendor udev rule. ─────────────────────────────────────────────────────
if [ -n "$UDEV_FROM" ] && [ -f "$UDEV_FROM" ]; then
    install -m 644 "$UDEV_FROM" /etc/udev/rules.d/99-signalhound.rules
    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger 2>/dev/null || true
    ok "Installed /etc/udev/rules.d/99-signalhound.rules"
fi

# ── 6. Build SoapySignalHound. Run cmake as the invoking user (not root) so
#       the clone + build artefacts end up in their ~/.cache, but cmake --install
#       runs as root so it can write to /usr/local. ───────────────────────────
INVOKING_USER="${SUDO_USER:-$USER}"
INVOKING_HOME="$(getent passwd "$INVOKING_USER" | cut -d: -f6)"
CACHE="$INVOKING_HOME/.cache/ares-sdr"
SRC="$CACHE/SoapySignalHound"
sudo -u "$INVOKING_USER" mkdir -p "$CACHE"
if [ ! -d "$SRC/.git" ]; then
    log "Cloning altaf-4-1/SoapySignalHound..."
    sudo -u "$INVOKING_USER" git clone --depth=1 https://github.com/altaf-4-1/SoapySignalHound.git "$SRC"
fi
log "Building SoapySignalHound..."
sudo -u "$INVOKING_USER" bash -c "cd '$SRC' && rm -rf build && cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j$(nproc)"
cmake --install "$SRC/build"
ldconfig

# ── 7. Verify. ───────────────────────────────────────────────────────────────
echo
ok "Done. Verification:"
if command -v SoapySDRUtil >/dev/null 2>&1; then
    echo "── SoapySDRUtil --info (last 8 lines) ──"
    SoapySDRUtil --info 2>&1 | tail -8
    echo "── SoapySDRUtil --find (any SignalHound device plugged in?) ──"
    SoapySDRUtil --find 2>&1 | head -30
else
    warn "SoapySDRUtil not on PATH — install SoapySDR with: ./install.sh --with-soapysdr"
fi
