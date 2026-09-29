#!/usr/bin/env python3
"""
ara-embed.py — sync private/ sources into the marked heredoc block in challenge 01's setup.

Authoring tool for the ARA tracks in elastic/instruqt-traqs-dev; nothing in a sandbox runs it.

Usage (tracks dir: --tracks-dir, else $ARA_TRACKS_DIR, else ./tracks):
  python3 tools/ara-embed.py <track-slug> --tracks-dir <traqs-dev>/tracks          # rewrite
  python3 tools/ara-embed.py <track-slug> --tracks-dir <traqs-dev>/tracks --check  # exit non-zero on drift

The setup script must contain exactly one marked block:
  # ---- BEGIN GENERATED FROM private/ (do not edit; run vestal_project tools/ara-embed.py) ----
  ...
  # ---- END GENERATED ----

The block is replaced with heredocs derived from:
  private/checks/ara_grade.py
  private/checks/<slug>/NN-name.py  (one per check challenge)
  private/heldout/*.json
  private/heldout/*.jsonl
  private/questions.json            (if present)
  private/heldout/questions.json    (if present)

Exit codes: 0 = ok (or no drift), 1 = drift detected (--check mode), 2 = usage error.
"""
from __future__ import annotations
import argparse, os, pathlib, sys, textwrap

MARKER_BEGIN = '# ---- BEGIN GENERATED FROM private/ (do not edit; run vestal_project tools/ara-embed.py) ----'
MARKER_END   = '# ---- END GENERATED ----'


def find_setup(track_dir: pathlib.Path) -> pathlib.Path:
    """Return the challenge 01 setup script."""
    ch01_dirs = sorted(track_dir.glob('01-*/'))
    if not ch01_dirs:
        sys.exit(f'No 01-* directory in {track_dir}')
    setup = ch01_dirs[0] / 'setup-elastic-serverless'
    if not setup.exists():
        sys.exit(f'No setup-elastic-serverless in {ch01_dirs[0]}')
    return setup


def generate_block(track_dir: pathlib.Path, slug: str) -> str:
    """Generate the content to place between the BEGIN/END markers."""
    private = track_dir / 'private'
    lines: list[str] = []

    def heredoc(dest: str, content: str, marker: str) -> None:
        lines.append(f"cat > {dest} << '{marker}'")
        lines.append(content.rstrip())
        lines.append(f'{marker}')

    # ara_grade.py
    grade_src = private / 'checks' / 'ara_grade.py'
    if grade_src.exists():
        heredoc('/opt/ara/checks/ara_grade.py', grade_src.read_text(), 'GRADE_EOF')
        lines.append('chmod 600 /opt/ara/checks/ara_grade.py')
        lines.append('')

    # Per-track check scripts  (private/checks/<slug>/NN-name.py)
    check_dir = private / 'checks' / slug
    if not check_dir.exists():
        # Try without slug prefix in dir name
        check_dir = private / 'checks'
    for check in sorted(check_dir.glob('*.py')) if check_dir.exists() else []:
        marker = f'CHECK_{check.stem.upper().replace("-", "_")}_EOF'
        dest = f'/opt/ara/checks/{slug}/{check.name}'
        lines.append(f'# {check.name}')
        heredoc(dest, check.read_text(), marker)
        lines.append(f'chmod 700 {dest}')
        lines.append('')

    # Held-out files  (private/heldout/*)
    heldout_dir = private / 'heldout'
    if heldout_dir.exists():
        for hf in sorted(heldout_dir.iterdir()):
            if hf.name in ('questions.json',):
                continue  # handled separately
            marker = f'HELDOUT_{hf.stem.upper().replace("-", "_")}_EOF'
            dest = f'/opt/ara/heldout/{hf.name}'
            lines.append(f'# {hf.name}')
            heredoc(dest, hf.read_text(), marker)
            lines.append(f'chmod 600 {dest}')
            lines.append('')

    # questions.json  (learner-staged; searched in private/ then private/heldout/)
    for qpath in [private / 'questions.json', private / 'heldout' / 'questions.json']:
        if qpath.exists():
            lines.append('# questions.json (staged hidden until Defend challenge unlocks it)')
            # written as elastic: root never follows a learner-made symlink in /home/elastic
            lines.append('runuser -u elastic -- mkdir -p /home/elastic/defend')
            lines.append("runuser -u elastic -- tee /home/elastic/defend/questions.json > /dev/null << 'Q_EOF'")
            lines.append(qpath.read_text().rstrip())
            lines.append('Q_EOF')
            lines.append('runuser -u elastic -- chmod 000 /home/elastic/defend/questions.json')
            lines.append('')
            break

    return '\n'.join(lines)


def embed(track_dir: pathlib.Path, slug: str, check_only: bool) -> bool:
    """Embed (or check) the generated block. Returns True if content matches."""
    setup = find_setup(track_dir)
    text = setup.read_text()

    if MARKER_BEGIN not in text:
        sys.exit(
            f'No BEGIN marker in {setup}. '
            'Add the markers before running ara-embed.py:\n'
            f'  {MARKER_BEGIN}\n'
            f'  {MARKER_END}'
        )
    if MARKER_END not in text:
        sys.exit(f'BEGIN marker found but no END marker in {setup}.')

    before, rest = text.split(MARKER_BEGIN, 1)
    _, after = rest.split(MARKER_END, 1)

    new_block = generate_block(track_dir, slug)
    new_text = (
        before
        + MARKER_BEGIN + '\n'
        + new_block + '\n'
        + MARKER_END
        + after
    )

    old_block = rest.split(MARKER_END, 1)[0].strip()
    matches = old_block.strip() == new_block.strip()

    if check_only:
        if not matches:
            print(f'DRIFT: {setup} — run ara-embed.py {slug} to regenerate', file=sys.stderr)
            return False
        print(f'OK: {setup}')
        return True

    if matches:
        print(f'No change: {setup}')
        return True

    setup.write_text(new_text)
    print(f'Updated: {setup}')
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description='Sync private/ into setup heredoc block.')
    parser.add_argument('slug', help='Track slug (e.g. cert-sk-ara-1-3-model-tier-and-agent-stack)')
    parser.add_argument('--check', action='store_true', help='Exit non-zero on drift without writing')
    parser.add_argument('--tracks-dir', default=os.environ.get('ARA_TRACKS_DIR', 'tracks'),
                        help='tracks/ directory of an instruqt-traqs-dev checkout')
    args = parser.parse_args()

    track_dir = pathlib.Path(args.tracks_dir) / args.slug
    if not track_dir.is_dir():
        sys.exit(f'Track not found: {track_dir}')

    ok = embed(track_dir, args.slug, args.check)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
