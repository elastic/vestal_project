step "Verifying module assets"
# The launcher fetched the full module bundle (checksummed tarball) into /opt/ara/src with the
# fetch-track-assets WSS. Confirm the paths this track needs before provisioning starts.
ASSETS_T0=$(date +%s)
ara_verify_assets() {
  local root="$1"
  for p in lib/defend.py; do   # TEMPLATE: every path this track needs
    [[ -e "${root}/${p}" ]] || { echo "  incomplete: missing ${p}"; return 1; }
  done
}
if ! ara_verify_assets /opt/ara/src; then
  echo "ERROR: module assets incomplete in /opt/ara/src ($(tr -d '\n' < /opt/ara/src/MANIFEST.json 2>/dev/null || echo 'no MANIFEST.json'))."
  false   # routes through the ERR trap so status.json + .failed are written
fi
