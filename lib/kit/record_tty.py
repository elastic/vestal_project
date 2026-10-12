#!/usr/bin/env python3
"""Drive the learner's terminal tools as elastic types them. Root-only test tool for solves.

    python3 record_tty.py <output.json> <schema.json> <answers.json>
    python3 record_tty.py --shell <timeout-s> <command>

Default: runs `runuser -u elastic -- python3 /opt/ara/lib/record.py <output.json> <schema.json>` on a
pseudo-terminal. For each field it waits for record.py's own prompt, then types the answer: the option's
number for a choice field, the text for a value field. The first choice field gets an out-of-range
number first, so the transcript also shows record.py's validation. Prints the transcript as PTY lines
and exits non-zero unless record.py exits 0 and the file it wrote holds exactly the answers.
answers.json maps each schema key to the value to record (an option's text for a choice field).

--shell: opens elastic's interactive login shell on a pseudo-terminal (the Terminal tab's .bashrc and
environment), types the command as the assignment gives it, and prints the transcript. Exits with the
command's own exit status.
"""
from __future__ import annotations

import json
import os
import pathlib
import pty
import re
import select
import subprocess
import sys
import time

PROMPT_CHOICE = "Choice (number): "
PROMPT_VALUE = "Value: "
INVALID = "Please enter a number between"
STEP_S = 20  # record.py answers each keystroke at once; a missing prompt after this long is a fail


class Term:
    def __init__(self, argv: list[str]):
        self.master, slave = pty.openpty()
        self.proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, close_fds=True,
                                     start_new_session=True)
        os.close(slave)
        self.buf = ""
        self.seen = 0

    def _read(self, wait: float) -> bool:
        ready, _, _ = select.select([self.master], [], [], wait)
        if not ready:
            return True
        try:
            chunk = os.read(self.master, 4096)
        except OSError:  # the child closed the terminal
            chunk = b""
        if not chunk:
            return False
        self.buf += chunk.decode(errors="replace").replace("\r", "")
        return True

    def wait_for(self, pattern: str, budget_s: float = STEP_S, regex: bool = False) -> re.Match | None:
        end = time.monotonic() + budget_s
        while True:
            rest = self.buf[self.seen:]
            m = re.search(pattern, rest) if regex else (re.search(re.escape(pattern), rest))
            if m:
                self.seen += m.end()
                return m
            left = end - time.monotonic()
            if left <= 0:
                self.show()
                sys.exit(f"PF-FAIL record_tty: no '{pattern.strip()}' within {round(budget_s)} s")
            if not self._read(min(left, 1.0)) and self.proc.poll() is not None:
                self.show()
                sys.exit(f"PF-FAIL record_tty: the program exited ({self.proc.returncode}) before '{pattern.strip()}'")

    def type(self, line: str) -> None:
        os.write(self.master, (line + "\n").encode())

    def finish(self) -> int:
        end = time.monotonic() + STEP_S
        while self.proc.poll() is None and time.monotonic() < end:
            if not self._read(0.5):
                break
        if self.proc.poll() is None:
            self.proc.kill()
        return self.proc.wait()

    def show(self) -> None:
        for line in self.buf.splitlines():
            print(f"PTY | {line}")


def record(out: str, schema_path: str, answers_path: str) -> None:
    schema = json.loads(pathlib.Path(schema_path).read_text())
    answers = json.loads(pathlib.Path(answers_path).read_text())
    pathlib.Path(out).unlink(missing_ok=True)
    term = Term(["runuser", "-u", "elastic", "--", "python3", "/opt/ara/lib/record.py", out, schema_path])
    showed_invalid = False
    for field in schema:
        want = answers[field["key"]]
        options = field.get("options") or []
        if options:
            if want not in options:
                sys.exit(f"PF-FAIL record_tty: {want!r} is not an option for {field['key']}")
            term.wait_for(PROMPT_CHOICE)
            if not showed_invalid:
                term.type(str(len(options) + 1))
                term.wait_for(INVALID)
                term.wait_for(PROMPT_CHOICE)
                showed_invalid = True
            term.type(str(options.index(want) + 1))
        else:
            term.wait_for(PROMPT_VALUE)
            term.type(str(want))
    rc = term.finish()
    term.show()
    if rc != 0:
        sys.exit(f"PF-FAIL record_tty: record.py exited {rc}")
    got = json.loads(pathlib.Path(out).read_text())
    if got != answers:
        sys.exit(f"PF-FAIL record_tty: {out} holds {json.dumps(got)[:400]}, expected {json.dumps(answers)[:400]}")
    print(f"PF-OK record_tty: {len(schema)} prompts answered through a terminal as elastic; {out} written by "
          f"{pathlib.Path(out).owner()} with the expected values"
          f"{'; an out-of-range entry was refused' if showed_invalid else ''}")


def shell(budget_s: float, command: str) -> None:
    term = Term(["runuser", "-l", "elastic"])
    term.type("PS1='ara$ '")
    term.wait_for(r"(?m)^ara\$ ", regex=True)  # the new prompt, not the echo of the line typed
    term.type(f'{command}; echo "ARA_DONE rc=$?"')
    m = term.wait_for(r"ARA_DONE rc=(\d+)", budget_s, regex=True)
    term.type("exit")
    term.finish()
    term.show()
    sys.exit(int(m.group(1)))


if __name__ == "__main__":
    if sys.argv[1] == "--shell":
        shell(float(sys.argv[2]), sys.argv[3])
    else:
        record(sys.argv[1], sys.argv[2], sys.argv[3])
