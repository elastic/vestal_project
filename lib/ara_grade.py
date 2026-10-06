"""
ara_grade.py - the shared private grader for ARA tracks (alignment round N3, 2026-10-06).

One canonical module for every track. Installed root-only at /opt/ara/checks/ara_grade.py,
straight from the assets bundle, by the "Installing graders" step of challenge 01's
setup-elastic-serverless (in the provision.sh it writes and launches), after /opt/ara/checks
exists:

    install -m 600 -o root -g root /opt/ara/src/lib/ara_grade.py /opt/ara/checks/ara_grade.py

Checks import it as before (sys.path.insert(0, "/opt/ara/checks"); from ara_grade import ...).
It is the union of the per-track copies it replaces; the alignment kit note lists every
difference between those copies and how each was decided.

Learner-visible rules it carries:
- Defend feedback (spec 18 section 1.8, ARA_DEFEND_FEEDBACK=1): grading runs exactly as Check
  does but records no grade and no results file. Only an answer message prints (Grade.verdict,
  answer_fail, _fail). Every other stop (fail, env_fail, an outage, the deadline) prints nothing,
  so the defend-feedback wrapper exits 11 and defend.py says "Select Check"; Check then shows it.
- Principle 8 (R-P8): a remote call that gets no usable answer is retried twice with a short
  backoff inside the deadline, then the check exits with "<Service> did not respond. Wait a moment
  and select Check again." and writes no grade. A remote failure is never the learner's miss.
- The 50 s deadline exits with a wait message and no grade before Instruqt's 60 s limit.
- Held-out text registered with register_heldout() never reaches a learner message (A23).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
from typing import Any, Iterable

GRADES_DIR = pathlib.Path("/opt/ara/grades")
RESULTS_DIR = pathlib.Path("/opt/ara/results")
THRESHOLDS = pathlib.Path("/opt/ara/thresholds.json")

# Defend feedback (spec 18 section 1.8). Set only by /opt/ara/checks/defend-feedback, which the
# learner runs through one sudoers entry (sudo resets the environment, so the learner cannot set
# it). The Defend checks still save their tries counter, so feedback and Check share one count.
FEEDBACK = os.environ.get("ARA_DEFEND_FEEDBACK") == "1"


# ── Learner-visible wording (A22) ─────────────────────────────────────────────

def outage_message(service: str) -> str:
    """The one outage form: "<Service> did not respond. Wait a moment and select Check again." """
    return f"{service} did not respond. Wait a moment and select Check again."


ES_UNREACHABLE = outage_message("Elasticsearch")
RERANKER_UNREACHABLE = outage_message("The reranker")
# The outage form for the LLM proxy (Joe 2026-10-06, "Align it"; R-P8 behaviour unchanged).
LLM_UNREACHABLE = outage_message("The LLM proxy")

CHECK_DEADLINE_S = 50
# The default deadline message: the check may be running learner code, so it blames neither.
DEADLINE_MESSAGE = ("The check ran out of time after {seconds} seconds and wrote no grade. Wait a "
                    "moment and select Check again. If this repeats, run your code once from the "
                    "notebook, time it, and look for a loop or retry that repeats model or search "
                    "calls.")
# For a check that runs no learner code: running out of time is the service, never the learner.
DEADLINE_SERVICE_MESSAGE = ("The check ran out of time after {seconds} seconds and wrote no grade: "
                            "Elasticsearch or a model endpoint was slow to respond. Wait a moment "
                            "and select Check again.")

MISSING_THRESHOLDS = ("This sandbox is missing its grading thresholds file, so the check cannot "
                      "score your work. Stop the track and start it again.")
DEFEND_REMEDY = ("Run python3 /opt/ara/lib/defend.py again to record your answers, then select "
                 "Check again.")


# ── Held-out scrub (A23) ──────────────────────────────────────────────────────

HELDOUT_PLACEHOLDER = "<held-out item>"
_SCRUB: list[tuple[str, str]] = []


# A cut-off copy of a held-out string is scrubbed once this many of its leading characters
# survive the cut, and only where a cut shows: the copy runs to the end of the text (closing
# quotes, brackets and whitespace aside) or is followed directly by an ellipsis. Held-out and
# dev queries share template openings, so the same opening mid-message is dev text and stays. Error text is cut before a check echoes it (child runners keep 120-300
# characters), so a held-out query that straddles the cut leaves only its start. 40 characters
# is about seven words: long enough that ordinary wording does not match one by chance, short
# enough to catch a query cut a little past its start.
SCRUB_PREFIX_MIN = 40


def _forms(secret: str) -> list[str]:
    """The ways a string can appear in exception text: as is, repr-escaped, JSON-escaped."""
    out = [secret, repr(secret)[1:-1], json.dumps(secret)[1:-1]]
    return [f for f in dict.fromkeys(out) if f]


def _atoms(form: str) -> list[str]:
    """form as regex pieces: each whitespace run matches any whitespace run, every other
    character matches itself in either case."""
    return [r"\s+" if piece.isspace() else re.escape(piece)
            for piece in re.findall(r"\s+|\S", form.strip())]


def _scrub_form(s: str, form: str, placeholder: str) -> str:
    atoms = _atoms(form)
    if not atoms:
        return s
    s = re.sub("".join(atoms), lambda m: placeholder, s, flags=re.I)
    # A truncated copy: the first SCRUB_PREFIX_MIN characters, then as much more of the
    # string as follows them.
    head, size = [], 0
    for a in atoms:
        head.append(a)
        size += 1
        if size >= SCRUB_PREFIX_MIN:
            break
    if size < SCRUB_PREFIX_MIN or len(head) == len(atoms):
        return s
    rest = [re.compile(a, re.I) for a in atoms[len(head):]]
    cut = re.compile(r"(?:\.\.\.|\u2026)|[\s\"')\]}]*\Z")
    out, pos = [], 0
    for m in re.finditer("".join(head), s, flags=re.I):
        if m.start() < pos:
            continue
        end = m.end()
        for r in rest:
            n = r.match(s, end)
            if not n:
                break
            end = n.end()
        if not cut.match(s, end):
            continue
        out.append(s[pos:m.start()] + placeholder)
        pos = end
    return "".join(out) + s[pos:]


def scrub(text: Any, secrets: Iterable[str] | None = None,
          placeholder: str = HELDOUT_PLACEHOLDER) -> str:
    """text with every secret replaced by placeholder, longest first. With no secrets given,
    uses the strings register_heldout() recorded (each with its own placeholder). A match
    ignores case and the width of whitespace runs. A copy cut off after at least
    SCRUB_PREFIX_MIN characters is replaced too, where it ends the text or meets an ellipsis."""
    s = "" if text is None else str(text)
    pairs = ([(x, placeholder) for x in secrets if isinstance(x, str) and x]
             if secrets is not None else list(_SCRUB))
    expanded = [(f, p) for x, p in pairs for f in _forms(x)]
    for form, p in sorted(expanded, key=lambda fp: len(fp[0]), reverse=True):
        s = _scrub_form(s, form, p)
    return s


def register_heldout(strings: Iterable[Any], placeholder: str = HELDOUT_PLACEHOLDER,
                     min_len: int = 4) -> None:
    """Record held-out strings (queries, ids, gold text) that no learner message may show.
    Every message _fail prints passes through scrub() from then on. Strings shorter than
    min_len are skipped: a two-letter id would blank out ordinary words."""
    for x in strings:
        if isinstance(x, str) and len(x.strip()) >= min_len:
            _SCRUB.append((x, placeholder))


def heldout_strings(items: Iterable[Any], keys: Iterable[str]) -> list[str]:
    """The string values of keys in each held-out item (dicts; lists of strings are flattened)."""
    keys = list(keys)
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for k in keys:
            v = item.get(k)
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, (list, tuple)):
                out.extend(x for x in v if isinstance(x, str))
    return out


# ── Fail paths ────────────────────────────────────────────────────────────────

def _fail(message: str) -> None:
    """Show a message without exiting: stdout for defend.py in feedback, fail-message in Check."""
    message = scrub(message)
    if FEEDBACK:
        print(message, flush=True)
        return
    print(f"fail-message: {message}", file=sys.stderr, flush=True)
    try:
        import subprocess
        subprocess.run(["fail-message", message], check=False)
    except Exception:
        pass


def _outage(message: str) -> None:
    """An outage or the deadline, not the learner: Check shows the message; feedback prints nothing."""
    if not FEEDBACK:
        _fail(message)


def fail(message: str) -> None:
    """Stop with a message and no grade: missing work, a skipped Build, an unreadable file, an
    environment fault. Silent in Defend feedback (defend.py then says "Select Check")."""
    _outage(message)
    sys.exit(1)


def env_fail(message: str) -> None:
    """An environment fault, not the learner's answers. Same as fail(); kept for M1 call sites."""
    fail(message)


def answer_fail(message: str) -> None:
    """Stop with a message about the learner's Defend answers: shown in Check and in feedback."""
    _fail(message)
    sys.exit(1)


def unreachable(what: str = "Elasticsearch", detail: Any = None) -> None:
    """Exit without a grade: the service, not the learner, failed (principle 8).
    what is a service name ("Elasticsearch") or a whole message ending in "." (ES_UNREACHABLE).
    detail (an exception or text) goes to the check log, never to the learner."""
    message = what if what.rstrip().endswith(".") else outage_message(what)
    if detail is not None:
        d = f"{type(detail).__name__}: {detail}" if isinstance(detail, BaseException) else str(detail)
        print(f"remote failure: {scrub(d)[:300]}", file=sys.stderr, flush=True)
    _outage(message)
    sys.exit(1)


# ── Deadline ──────────────────────────────────────────────────────────────────

_DEADLINE_AT: float | None = None  # monotonic time the deadline fires; remote() budgets against it


def deadline(seconds: int = CHECK_DEADLINE_S, message: str | None = None) -> None:
    """Stop with a wait message, and no grade, before Instruqt's 60 s check limit stops the
    script silently. Call once, before any learner code or remote call. The handler exits the
    process directly, so a broad except in learner code cannot swallow it. Silent in feedback."""
    import signal

    global _DEADLINE_AT
    msg = (message or DEADLINE_MESSAGE).replace("{seconds}", str(seconds))

    def _expire(signum, frame):
        _outage(msg)
        os._exit(1)

    _DEADLINE_AT = time.monotonic() + seconds
    signal.signal(signal.SIGALRM, _expire)
    signal.alarm(seconds)


def cancel_deadline() -> None:
    """Cancel the deadline() alarm. Grade.write calls it: once a grade is recorded, the check
    is no longer at risk of Instruqt's limit, and "wrote no grade" would be false."""
    global _DEADLINE_AT
    if _DEADLINE_AT is None:
        return
    import signal
    signal.alarm(0)
    _DEADLINE_AT = None


# ── Remote failures (spec 09 principle 8, R-P8) ───────────────────────────────

REMOTE_RETRIES = 2
REMOTE_ATTEMPTS = REMOTE_RETRIES + 1
REMOTE_BACKOFF_S = (1.0, 3.0)
_OUTAGE_STATUS = (401, 403, 408, 429)
_OUTAGE_NAMES = {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError",
                 "ServiceUnavailableError", "AuthenticationError", "PermissionDeniedError",
                 "ConnectionError", "ConnectionTimeout", "TransportError", "TlsError", "SSLError",
                 "ConnectTimeout", "ReadTimeout", "RemoteDisconnected", "RemoteCallFailed"}
_LOCAL_OS_ERRORS = (FileNotFoundError, FileExistsError, IsADirectoryError, NotADirectoryError,
                    PermissionError)


def is_outage(exc: BaseException) -> bool:
    """True when a call got no usable answer: no response, a timeout, 401/403 (the platform's
    key or access), 408, 429 or a 5xx (departure X3). Any other 4xx is the learner's request, and
    a local file error is not a remote call."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "meta", None), "status", None)
    if isinstance(status, int):
        return status in _OUTAGE_STATUS or status >= 500
    if type(exc).__name__ in _OUTAGE_NAMES:
        return True
    try:
        from elastic_transport import TransportError
        if isinstance(exc, TransportError):
            return True
    except Exception:
        pass
    return isinstance(exc, OSError) and not isinstance(exc, _LOCAL_OS_ERRORS)


def outage_text(text: Any) -> bool:
    """is_outage for an error a child process recorded as text: "Type(...)" or "Type: message"."""
    t = str(text or "").strip()
    if t.startswith("error: "):
        t = t[len("error: "):]
    m = re.search(r"(?:\w\(|status=|Error code: )(\d{3})\b", t)
    if m:
        status = int(m.group(1))
        return status in _OUTAGE_STATUS or status >= 500
    name = re.match(r"\s*([A-Za-z_][\w.]*)", t)
    return bool(name) and name.group(1).rsplit(".", 1)[-1] in _OUTAGE_NAMES


def _call_with_retries(fn, args, kwargs, message: str):
    last: BaseException | None = None
    for attempt in range(REMOTE_ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if not is_outage(exc):
                raise
            last = exc
            if attempt == REMOTE_ATTEMPTS - 1:
                break
            wait = REMOTE_BACKOFF_S[min(attempt, len(REMOTE_BACKOFF_S) - 1)]
            if _DEADLINE_AT is not None and time.monotonic() + wait + 5 > _DEADLINE_AT:
                break  # no time left for another try: still the service, never the learner
            time.sleep(wait)
    unreachable(message, f"{type(last).__name__} after {REMOTE_ATTEMPTS} attempts: {last}")


def remote(fn, *args, what: str = "Elasticsearch", **kwargs):
    """Call fn(*args, **kwargs). Retry an outage twice with backoff while the deadline allows,
    then exit through unreachable(what). Any other exception is re-raised unchanged."""
    return _call_with_retries(fn, args, kwargs, what)


def remote_call(fn, *args, _message: str = ES_UNREACHABLE, **kwargs):
    """remote() with a whole message (ES_UNREACHABLE, LLM_UNREACHABLE, ...) in place of a name."""
    return _call_with_retries(fn, args, kwargs, _message)


# Exception types the model gateway's client raises (openai, and httpx beneath it). The
# Elasticsearch client raises its own types from elasticsearch / elastic_transport.
_LLM_MODULES = ("openai", "httpx", "httpcore", "anthropic")
_LLM_NAMES = {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError",
              "AuthenticationError", "PermissionDeniedError"}
_ES_MODULES = ("elasticsearch", "elastic_transport")
# ara_pack / ara_attrib RemoteCallFailed starts with the call's label: "completion endpoint
# unreachable after ..." is the model; "search", "rerank" and "embed" go through Elasticsearch.
_LLM_LABEL = re.compile(r"\s*(?:chat_)?completion\b", re.I)


def outage_service_message(exc: BaseException) -> str:
    """The outage message that names the service an uncaught exception came from: the LLM
    proxy for the model client's errors, Elasticsearch for the Elasticsearch client's. Reads
    the exception, then its cause chain; anything it cannot place is Elasticsearch, the
    service every check calls."""
    seen: set[int] = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        root = (type(e).__module__ or "").split(".")[0]
        if root in _LLM_MODULES:
            return LLM_UNREACHABLE
        if root in _ES_MODULES:
            return ES_UNREACHABLE
        if type(e).__name__ == "RemoteCallFailed" and _LLM_LABEL.match(str(e)):
            return LLM_UNREACHABLE
        if type(e).__name__ in _LLM_NAMES:
            return LLM_UNREACHABLE
        e = e.__cause__ or e.__context__
    return ES_UNREACHABLE


def _excepthook(tp, exc, tb):
    # Safety net for a remote call made outside remote(): an outage still writes no grade and
    # shows the wait message naming that service (silent in feedback), not only a traceback.
    sys.__excepthook__(tp, exc, tb)
    if isinstance(exc, Exception) and is_outage(exc):
        _outage(outage_service_message(exc))


sys.excepthook = _excepthook


# ── Grade ─────────────────────────────────────────────────────────────────────

def to_jsonable(obj: Any) -> Any:
    """Plain JSON types for a client response or NumPy value (spec 09 T12): unwraps .body,
    converts NumPy scalars. Checks serialize through this, never their own JSONEncoder."""
    if hasattr(obj, "body") and not isinstance(obj, (dict, list, str, bytes)):
        obj = obj.body
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if hasattr(obj, "item") and callable(obj.item) and not isinstance(obj, (str, bytes)):
        return obj.item()
    return obj


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Grade:
    def __init__(self, challenge: str, tries: str | os.PathLike | None = None):
        self.challenge = challenge
        self.criteria: list[dict] = []
        self._failed: list[str] = []
        self._first_failure: str | None = None
        self.tries = pathlib.Path(tries) if tries else None
        self.guides: dict[str, str] = {}

    def criterion(self, name: str, passed: bool, message: str, guide: str | None = None) -> None:
        self.criteria.append({"name": name, "passed": passed, "message": message})
        if guide:
            self.guides[name] = guide
        if not passed and self._first_failure is None:
            self._first_failure = message
            self._failed.append(message)

    def metric(self, name: str, value: Any) -> None:
        self.criteria.append({"name": name, "value": value, "is_metric": True})

    def write(self, path: str | None = None, passed: bool | None = None) -> None:
        """Record the grade, root-only, by rename: a reader never sees a half-written file. The
        deadline is cancelled first: grading is over, so it can no longer report "wrote no
        grade" after this grade, or cut the write short."""
        cancel_deadline()
        if FEEDBACK:
            return
        GRADES_DIR.mkdir(parents=True, exist_ok=True)
        out = path or str(GRADES_DIR / f"{self.challenge}.json")
        data = {
            "challenge": self.challenge,
            "written_at": _now(),
            "passed": (self._first_failure is None) if passed is None else passed,
            "criteria": self.criteria,
        }
        write_no_follow(out, json.dumps(to_jsonable(data), indent=2), mode=0o600)

    def results_for_defend(self, path: str, metrics: dict) -> None:
        """Results defend.py reads. Not written in feedback. Written by rename, never through a
        planted symlink (T20), mode 644."""
        if FEEDBACK:
            return
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        write_no_follow(p, json.dumps(to_jsonable({"challenge": self.challenge, "written_at": _now(),
                                                   "metrics": metrics}), indent=2))

    def apply_guidance(self) -> None:
        """Grading standard section 7a. A criterion's counter rises only when its message is the
        one shown (the first failure) and resets when it passes. From the second showing, the
        criterion's guide is appended. Check and Defend feedback share the counter (both run
        verdict). The counter file is root-only (600): only the check reads it. A missing directory
        is created root-only; an existing one keeps its mode, because it may be shared with files
        others read (/opt/ara/results holds what defend.py reads). No-op without tries."""
        if self.tries is None:
            return
        try:
            tries = json.loads(self.tries.read_text())
        except Exception:
            tries = {}
        if not isinstance(tries, dict):
            tries = {}
        rows = [c for c in self.criteria if not c.get("is_metric")]
        shown = next((c for c in rows if not c["passed"]), None)
        for c in rows:
            if c["passed"]:
                tries[c["name"]] = 0
            elif c is shown:
                tries[c["name"]] = int(tries.get(c["name"], 0) or 0) + 1
        try:
            if not self.tries.parent.exists():
                self.tries.parent.mkdir(mode=0o700, parents=True)
            write_no_follow(self.tries, json.dumps(tries), mode=0o600)
        except OSError:
            pass
        if shown is not None and shown["name"] in self.guides and tries.get(shown["name"], 0) >= 2:
            shown["message"] = f'{shown["message"]} {self.guides[shown["name"]]}'
            self._first_failure = shown["message"]
            if self._failed:
                self._failed[0] = shown["message"]

    def verdict(self, passed: bool | None = None) -> None:
        """Write the grade and exit 1 on a failure, showing the first failed criterion's message.
        passed=True records a pass with failed criteria kept in the grade (capstone tier 75,
        09 section 6) and shows no message."""
        self.apply_guidance()
        self.write(passed=passed)
        if self._first_failure and passed is not True:
            _fail(self._first_failure)
            sys.exit(1)


# ── Files ─────────────────────────────────────────────────────────────────────

def write_no_follow(path, text: str, mode: int = 0o644) -> None:
    """Write a file by rename (grading standard T20). A directory the learner owns may hold a
    planted symlink at the name; write_text() would follow it, a new file renamed over the name
    replaces the link instead. The mode is set on the open descriptor, never by path."""
    import tempfile
    path = pathlib.Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), mode)
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_learner_text(path: str | pathlib.Path) -> str | None:
    """Read a file in the learner's home as root without following a symlink (T20). None when it
    does not exist. A symlink (at the file or its directory), a directory or any other non-regular
    file ends the check with a message and no grade. Bytes that are not UTF-8 raise
    UnicodeDecodeError, a ValueError, as invalid JSON does."""
    import errno
    import stat
    p = str(path)
    parent = os.path.dirname(p)
    if os.path.islink(parent):  # the directory the learner controls; /home itself is not theirs
        fail(f"{parent} is a symbolic link, so the check will not read {os.path.basename(p)} "
             "through it. Replace it with a regular directory, save the file again, then select Check.")
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as e:
        if e.errno == errno.ELOOP:
            fail(f"{p} is a symbolic link. The check reads only a regular file there: delete the "
                 "link, save the file again, then select Check.")
        fail(f"{p} can't be read ({e.strerror}). Save the file again, then select Check.")
    if not stat.S_ISREG(os.fstat(fd).st_mode):  # before fdopen, which rejects a directory itself
        os.close(fd)
        fail(f"{p} is not a regular file. Save the file again, then select Check.")
    with os.fdopen(fd, "rb") as f:
        return f.read().decode("utf-8")


# Files the learner can write (integrity review XC-5). A hand-edited file that is not valid JSON,
# or not the shape the notebook or defend.py writes, ends the check with a learner message and
# no grade, never a traceback.
def unreadable(path, remedy: str) -> None:
    fail(f"{pathlib.Path(path).name} is not in the form this check reads; it may have been "
         f"edited by hand. {remedy}")


def learner_json(path, remedy: str, shape=dict):
    """Parse a learner-writable JSON file; anything else goes through unreadable(). Read with
    read_learner_text, so a symlink planted at the name (or its directory) is never followed."""
    try:
        text = read_learner_text(path)
        data = None if text is None else json.loads(text)
    except (OSError, UnicodeDecodeError, ValueError):
        data = None
    if not isinstance(data, shape):
        unreadable(path, remedy)
    return data


def decision_answers(path="/home/elastic/defend/decision.json") -> dict:
    """decision.json as defend.py writes it, as {question_id: answer}. Every answer is an object
    with a string question_id, and its choice and reason, when present, are strings."""
    rows = learner_json(path, DEFEND_REMEDY).get("answers", [])
    if not (isinstance(rows, list) and all(
            isinstance(a, dict) and isinstance(a.get("question_id"), str)
            and all(isinstance(a.get(k, ""), str) for k in ("choice", "reason")) for a in rows)):
        unreadable(path, DEFEND_REMEDY)
    return {a["question_id"]: a for a in rows}


def thresholds(section: str) -> dict:
    """Graded numbers for one challenge, from the file the ch01 setup installs (spec 18 section 1.7)."""
    try:
        return json.loads(THRESHOLDS.read_text())[section]
    except Exception:
        fail(MISSING_THRESHOLDS)


def parse_llm_json(text: str | None) -> dict | None:
    """Strip Markdown code fences and parse a JSON object. None on failure or when the JSON is
    not an object (grading standard T8)."""
    if text is None:
        return None
    raw = str(text).strip()
    if raw.startswith("```"):
        inner = "\n".join(raw.split("\n")[1:]).strip()
        if inner.endswith("```"):
            inner = inner[:-3].strip()
        raw = inner
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


# ── Number matching (1.2 and 1.C answers) ─────────────────────────────────────
# Number words become digits, $ and thousands separators go.
_SMALL = {w: i for i, w in enumerate(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen '
    'fourteen fifteen sixteen seventeen eighteen nineteen'.split())}
_TENS = {w: 10 * i for i, w in enumerate(
    'twenty thirty forty fifty sixty seventy eighty ninety'.split(), start=2)}
_SCALES = {'hundred': 100, 'thousand': 1000, 'million': 1000000}
_NUM_WORD = '|'.join(sorted({**_SMALL, **_TENS, **_SCALES}, key=len, reverse=True))
_NUM_SPAN = re.compile(rf'\b(?:{_NUM_WORD})(?:\s+(?:and\s+)?(?:{_NUM_WORD}))*\b')


def _span_to_digits(span):
    numbers = []; total = 0; current = 0; last = None; big = 0
    words = span.split()
    for i, w in enumerate(words):
        if w == 'and':
            # "one hundred and twenty" and "one hundred and fifty thousand" are one number, and
            # so is "two million four hundred and fifty thousand": the next scale is below the
            # largest one already in this number. "three thousand five hundred and seven
            # thousand five hundred" is two numbers: the next scale repeats the one before.
            after = words[i + 1:i + 4]
            nxt = next((_SCALES[a] for a in after if a in _SCALES and a != 'hundred'), None)
            joined = (i > 0 and words[i - 1] == 'hundred' and after and after[0] not in _SCALES
                      and (nxt is None or big == 0 or nxt < big))
            if not joined:
                numbers.append(total + current); total = 0; current = 0; last = None; big = 0
            continue
        if w in _SCALES:
            if w == 'hundred':
                current = (current or 1) * 100
            else:
                total += (current or 1) * _SCALES[w]; current = 0
                big = big or _SCALES[w]
            last = 'scale'
            continue
        kind = 'tens' if w in _TENS else 'small'
        # "five six" is two numbers; "twenty four" is one.
        if last in ('small', 'tens') and not (last == 'tens' and kind == 'small' and _SMALL[w] < 10):
            numbers.append(total + current); total = 0; current = 0; big = 0
        current += _TENS.get(w, _SMALL.get(w, 0)); last = kind
    numbers.append(total + current)
    return ' '.join(str(n) for n in numbers)


def normalise(text):
    s = str(text).lower().replace('$', ' ')
    s = re.sub(r'(?<=[a-z])-(?=[a-z])', ' ', s)               # twenty-four -> twenty four
    s = re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', s)              # 24,500 -> 24500
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'(?<![\w.])(\d+) (thousand|million)\b',        # 10 thousand -> 10000
               lambda m: str(int(m.group(1)) * _SCALES[m.group(2)]), s)
    return _NUM_SPAN.sub(lambda m: _span_to_digits(m.group(0)), s)


def contains_value(answer, gold):
    """True if the answer states the gold value. gold is a string, or a list of
    equivalent forms of which any one is enough."""
    norm = normalise(answer)
    for form in (gold if isinstance(gold, list) else [gold]):
        g = normalise(form)
        pat = re.escape(g)
        if g[:1].isdigit():
            pat = r'(?<![\w.\-])' + pat
        if g[-1:].isdigit():
            pat = pat + r'(?!\.?\d)'
        if g and re.search(pat, norm):
            return True
    return False


def money_forms(text):
    """Also read "12.5k", "12.5 thousand" and "12,500.00" as 12500, then normalise."""
    s = str(text)
    s = re.sub(r'(\d+(?:\.\d+)?)\s*(?:k\b|thousand\b)',
               lambda m: str(round(float(m.group(1)) * 1000)), s, flags=re.I)
    s = re.sub(r'(\d)\.0+(?!\d)', r'\1', s)
    return s


# ── Learner-visible numbers (A16) ─────────────────────────────────────────────

def fmt_num(value: Any) -> str:
    """A number as a learner reads it: thousands separators from 1,000 up, the same as every
    assignment writes them. Whole floats lose ".0" only from 1,000 up. Anything else is str()."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        if abs(value) >= 1000:
            return f"{int(value):,}" if value.is_integer() else f"{value:,}"
        return str(value)
    return f"{value:,}" if abs(value) >= 1000 else str(value)
