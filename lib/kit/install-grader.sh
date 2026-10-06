# N3 migration only (Phase B, last, and only after Joe's call): the shared grader, root-only, from
# the bundle. Goes in "Installing graders", after /opt/ara/checks exists and before the generated
# block; the track then deletes private/checks/ara_grade.py so ara-embed.py stops embedding a copy.
install -m 600 -o root -g root /opt/ara/src/lib/ara_grade.py /opt/ara/checks/ara_grade.py
