"""ara-loop.py: argument handling, exit codes, and the nDCG mean over policy records."""
import importlib.util
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
spec = importlib.util.spec_from_file_location("ara_loop_main", pathlib.Path(__file__).resolve().parent / "ara-loop.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
import ara_loop_cli as C  # noqa: E402
from test_ara_loop_cli import Deps, ATTACH  # noqa: E402


def test_usage_and_exit_codes(capsys):
    assert M.main([]) == 2 and M.main(["gate"]) == 2 and M.main(["fly", "p1"]) == 2
    assert M.main(["candidate", "nope"], make_deps=lambda env: Deps({})) == 1
    assert "no proposal nope" in capsys.readouterr().out
    assert M.main(["candidate", "p1"], make_deps=lambda env: Deps({"p1": ATTACH})) == 0
    assert "candidate tina-compliance--cand-p1 built" in capsys.readouterr().out


def test_outage_exit_code(capsys):
    class Down(Deps):
        def measure(self, label, agent_id):
            raise M.ABError("down", 503)
    d = Down({"p1": ATTACH})
    C.candidate(d, "p1")
    assert M.main(["gate", "p1"], make_deps=lambda env: d) == 3


def test_with_ndcg_means_policy_records_only():
    recs = [{"retrieval": {"ndcg_at_5": 0.6}}, {"retrieval": {"ndcg_at_5": 0.8}}, {"question_id": "q"}]
    assert abs(M.with_ndcg({"x": 1}, recs)["ndcg_at_5"] - 0.7) < 1e-9
    assert M.with_ndcg({}, [{}])["ndcg_at_5"] is None
