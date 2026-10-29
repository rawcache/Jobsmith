"""Every colour pair Jobsmith draws meets WCAG AA (scripts/contrast.py reads them from the files themselves)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("contrast", Path(__file__).parents[1] / "scripts/contrast.py")
contrast = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contrast)


def test_every_pair_meets_aa():
    assert contrast.check() == []


def test_the_checker_reads_the_accent_from_each_surface():
    s = contrast.surfaces()
    assert s["dashboard, light"][0]["accent"] == "#9a3412" and s["dashboard, dark"][0]["accent"] == "#e07a4f"
    assert s["extension popup, light"][0]["accent"] == "#9a3412" and s["extension popup, dark"][0]["accent"] == "#e07a4f"
    assert s["extension panel"][0]["accent"] == "#9a3412" and s["terminal app"][0]["ember"] == "#e07a4f"


def test_a_pair_below_aa_is_reported():
    low = {"a page": ({"muted": "#75716a", "paper": "#f2f0ec", "ink": "#16161d"},
                      [("muted", "paper", contrast.TEXT), ("ink", "paper", contrast.TEXT)])}
    assert contrast.check(low) == ["a page: muted #75716a on paper #f2f0ec is 4.26:1, needs 4.5:1"]   # the panel's old grey
    assert round(contrast.ratio("#ffffff", "#9a3412"), 2) == 7.31
    assert contrast.over("rgb(255 255 255 / .5)", "#000000") == "#808080"


def test_text_faded_with_opacity_is_reported(monkeypatch, tmp_path):
    """Opacity fades text below what its colours say (the finished setup cards were 2.5:1 at opacity .6)."""
    (tmp_path / "s.css").write_text(".done a { opacity: .6; }\n.btn:disabled { opacity: .5; }\n.dots i { opacity: .3; }\n"
                                    "@keyframes spin { from { opacity: 0.2 } to { opacity: 1 } }\n"
                                    ".soon , .chip:disabled { opacity : 60%; }\n.transition-note { opacity: .7 }\n"
                                    ".shown { opacity: 1; }\n.b:is(.x, .y):disabled, [title='a,b']:disabled { opacity: .5 }\n"
                                    ":is(.active, :disabled) { opacity: .5 }\n.go:not(:disabled) { opacity: .5 }\n"
                                    ".go:disabled:hover { opacity: .5 }\n"
                                    ":is(:disabled), :where(button:disabled, [disabled]) { opacity: .5 }\n"
                                    ":is(button:disabled) + a { opacity: .5 }\n"
                                    '[title=":is(:disabled)"] { opacity: .5 }\n[title="("]:disabled { opacity: .5 }\n'
                                    "button:disabled.foo\\+bar { opacity: .5 }\nbutton.foo\\[x:disabled + a { opacity: .5 }\n"
                                    "[title='a\\'b']:disabled, .live { opacity: .5 }")
    monkeypatch.setattr(contrast, "ROOT", tmp_path)
    monkeypatch.setattr(contrast, "SHEETS", ("s.css",))
    assert contrast.fades() == ["s.css: .done a fades to opacity .6; use a colour token instead",
                                "s.css: .soon fades to opacity 60%; use a colour token instead",
                                "s.css: .transition-note fades to opacity .7; use a colour token instead",
                                "s.css: :is(.active, :disabled) fades to opacity .5; use a colour token instead",
                                "s.css: .go:not(:disabled) fades to opacity .5; use a colour token instead",
                                "s.css: :is(button:disabled) + a fades to opacity .5; use a colour token instead",
                                "s.css: [title=\":is(:disabled)\"] fades to opacity .5; use a colour token instead",
                                "s.css: button.foo\\[x:disabled + a fades to opacity .5; use a colour token instead",
                                "s.css: .live fades to opacity .5; use a colour token instead"]
