# Wait for provisioning: the spec 02 section 3.6 block, in every setup after 01, since a skip can arrive early.
for i in $(seq 1 648); do
  [[ -f /opt/ara/.ready ]] && break
  if [[ -f /opt/ara/.failed ]]; then echo "Provisioning failed:"; cat /opt/ara/.failed; exit 1; fi
  sleep 5
done
[[ -f /opt/ara/.ready ]] || { echo "Provisioning did not finish in 54 minutes. Stop the track and start it again."; exit 1; }
