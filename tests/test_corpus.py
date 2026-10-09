"""PRD Clay integration + Protocol: the committed corpus must satisfy the selection rules."""
import pandas as pd

COLS = ["repo", "stars", "open_issues", "language", "uses_actions", "fixes_links", "domain", "held_out"]


def test_repos_csv_meets_prd_rules():
    df = pd.read_csv("corpus/repos.csv")
    assert list(df.columns) == COLS
    assert 12 <= len(df) <= 20                      # PRD: a 12 to 20 repo corpus
    assert df.repo.is_unique and (df.language == "Python").all()
    assert (df.fixes_links >= 30).all() and (df.uses_actions > 0).all()
    assert df.domain.nunique() >= 5                 # diversity: not twelve web frameworks
    held = df[df.held_out.astype(str).str.lower() == "true"]
    assert len(held) >= 2 and held.domain.nunique() >= 2
