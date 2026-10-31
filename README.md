# ballmonitor

Simple, open, fully-tweakable sports models (college football bowls and CFP, recruiting,
MLB pitches and bullpens, college baseball and softball, running races, award and poll
ballots) and sports games (27K, Triple Play, Pitch Guesser). Every model has the same
output format, keeps every weight and formula in an editable `config.toml`, and documents
its assumptions. The public site is a static build on GitHub Pages, refreshed by
`.github/workflows/daily-build.yml`.

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,data,ml,ingest]'
source .venv/bin/activate

ballmonitor list
ballmonitor run ncaaf_bowls
ballmonitor run race_time --set riegel_exponent=1.08
ballmonitor serve                                  # browser UI at http://127.0.0.1:8765
ballmonitor update-and-build --models ncaaf_bowls  # fetch + rebuild dist/
pytest
```

See [CLAUDE.md](CLAUDE.md) for the architecture and conventions, each model's `MODEL.md`
for its method and assumptions, [ROADMAP.md](ROADMAP.md) for planned models, and
[attic/ballmonitor-2019/NOTES.md](attic/ballmonitor-2019/NOTES.md) for code saved from the
2019 Ball Monitor site.
