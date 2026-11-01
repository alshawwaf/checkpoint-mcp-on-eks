"""Every diagram has a dark variant generated from its light source, and the
README serves both through <picture>."""

import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("make_dark", os.path.join(ROOT, "docs", "img", "make_dark.py"))
make_dark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_dark)


def test_dark_variants_are_current():
    assert make_dark.main(check=True) == 0


def test_readme_serves_both_themes():
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    for light, dark in make_dark.targets():
        name, dname = os.path.basename(light), os.path.basename(dark)
        if f"docs/img/{name}" in readme:
            assert f'media="(prefers-color-scheme: dark)" srcset="docs/img/{dname}"' in readme, dname
