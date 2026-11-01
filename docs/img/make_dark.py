"""Generate the dark-mode variant of every diagram from its light SVG.

    python docs/img/make_dark.py          # writes <name>-dark.svg next to each <name>.svg
    python docs/img/make_dark.py --check  # exit 1 if any dark file is stale (used by tests)

Only colours change, so the geometry -- already checked with lint-diagrams.js --
is identical in both themes. The README serves the right one with
<picture><source media="(prefers-color-scheme: dark)" ...>.
"""

from __future__ import annotations

import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# light -> dark (GitHub dark palette; brand gradient unchanged). Order matters:
# the canvas uses the attribute form fill="#ffffff", boxes use the CSS form.
PALETTE = [
    ('fill="#ffffff"', 'fill="#0d1117"'),   # canvas
    ("fill:#ffffff", "fill:#161b22"),       # boxes (.node, .pill)
    ("#1c2036", "#e6edf3"),                 # primary text
    ("#565d78", "#b1bac4"),                 # secondary text
    ("#8489a0", "#8b949e"),                 # faint text
    ("#e2e5f1", "#30363d"),                 # canvas / zone borders
    ("#f7f8fd", "#11161d"),                 # zone panels, "+N more" box
    ("#eef0f9", "#1b2130"),                 # cluster panel
    ("#cfd4e6", "#434b57"),                 # cluster border
    ("#d9ddeb", "#3d444d"),                 # box borders
    ("#c9cede", "#4a525d"),                 # dashed box border
    ("#fdf4fa", "#2a1626"),                 # agent / highlight fill
    ("#8b90a8", "#8b949e"),                 # grey edges + arrowheads
    ("#e0117f", "#ff4fa8"),                 # magenta request path
    ("#0ea472", "#3fb950"),                 # green return path
]


def darken(svg):
    for light, dark in PALETTE:
        svg = svg.replace(light, dark)
    return svg


def targets():
    for path in sorted(glob.glob(os.path.join(HERE, "*.svg"))):
        if not path.endswith("-dark.svg"):
            yield path, path[:-4] + "-dark.svg"


def main(check=False):
    stale = []
    for light, dark in targets():
        with open(light, encoding="utf-8") as fh:
            want = darken(fh.read())
        have = open(dark, encoding="utf-8").read() if os.path.exists(dark) else None
        if have != want:
            if check:
                stale.append(os.path.basename(dark))
            else:
                with open(dark, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(want)
                print(f"wrote {os.path.basename(dark)}")
    if stale:
        print("stale dark diagrams (run python docs/img/make_dark.py):", ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv))
