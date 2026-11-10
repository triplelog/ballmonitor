"""The data-table CSV builder (ballmonitor/data_tables): passer rating and columns that match tables.toml."""

import pytest

from ballmonitor.data_tables import build
from ballmonitor.web import tables


def test_passer_rating_hand_calculated():
    # 20 of 30, 250 yards, 2 TD, 1 INT: (1.8333 + 1.3333 + 1.3333 + 1.5417) / 6 * 100 = 100.7
    assert build.passer_rating(20, 30, 250, 2, 1) == 100.7
    assert build.passer_rating(10, 10, 200, 4, 0) == 158.3          # every part capped: a perfect game
    assert build.passer_rating(0, 10, 0, 0, 5) == 0.0               # every part floored
    assert build.passer_rating(0, 0, 0, 0, 0) == 0.0


@pytest.mark.parametrize("table_id, columns", [
    ("qb-games", build.NFL_QB_COLUMNS),
    ("nba-games", build.BASKETBALL_COLUMNS),
    ("wnba-games", build.BASKETBALL_COLUMNS),
])
def test_tables_toml_names_only_columns_the_csv_has(table_id, columns):
    t = next(x for x in tables.load()["table"] if x["id"] == table_id)
    named = set(t["order"]) | set(t.get("columns", {})) | {t["sort"]["column"]}
    assert named <= set(columns), named - set(columns)
    assert t["path"] in ("qb_games/", "nba_games/", "wnba_games/")
