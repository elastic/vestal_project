# ── Brief server ──────────────────────────────────────────────────────────────
# One launcher block for every track (alignment N2). Copy the whole brief/ (dotfiles too), and
# stop if the page is missing: a blank pane is worse than a failed setup.
ARA_BRIEF_SRC="/opt/ara/src/modules/<m>/<track>/brief"
mkdir -p /opt/ara/brief
cp -r "${ARA_BRIEF_SRC}/." /opt/ara/brief/
[[ -f /opt/ara/brief/index.html ]] || { echo "Brief page missing from ${ARA_ASSETS_TAG}."; exit 1; }
echo '{"ready": false}' > /opt/ara/brief/status.json
nohup python3 -m http.server 5000 --directory /opt/ara/brief \
  >/var/log/ara-brief.log 2>&1 &
echo "Brief server started on port 5000 (pid $!)"
