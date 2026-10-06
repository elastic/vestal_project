# Close the assets copy: every learner-facing file is staged above. The bundle also holds other
# modules' held-out items, so only root (checks, solves) reads it from here (final audit lane 2,
# MUST-FIX 1; integrity review XC-1). No staged learner file may still point into it.
if grep -rlsF /opt/ara/src /home/elastic/notebooks; then
  echo "ERROR: a staged notebook still reads /opt/ara/src, which is about to close."; false
fi
chmod 700 /opt/ara/src
