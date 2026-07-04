"""Harvest golden outputs from a .ipynb WITHOUT re-executing it.

The notebook JSON stores executed outputs per cell. This dumps them to a
goldens.json the parity test can assert against, plus a cell map for the
coverage table.

Usage:
    python extract_goldens.py analysis.ipynb goldens.json

Caveats:
- Displayed numbers are ROUNDED for display; parity tests parsing these need
  tolerance matched to the printed precision. Re-execute for exact goldens.
- Non-monotonic execution_count = cells were run out of order; the stored
  outputs may not reproduce from a clean top-to-bottom run. Re-execute first:
    jupyter nbconvert --to notebook --execute analysis.ipynb
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def harvest(nb_path: str) -> dict:
    nb = json.loads(Path(nb_path).read_text(encoding="utf-8"))
    cells = []
    exec_counts: list[int] = []
    n_unexecuted = 0
    n_error_cells = 0
    for i, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        ec = cell.get("execution_count")
        if isinstance(ec, int):
            exec_counts.append(ec)
        else:
            n_unexecuted += 1
        outputs = []
        for out in cell.get("outputs", []):
            ot = out.get("output_type")
            if ot == "stream":
                # stderr streams (warnings, progress bars) are NOT goldens —
                # mark them so the parity author can't mistake them for results.
                outputs.append({"kind": "stream", "name": out.get("name", "stdout"),
                                "text": "".join(out.get("text", []))})
            elif ot in ("execute_result", "display_data"):
                txt = out.get("data", {}).get("text/plain")
                if txt is not None:
                    outputs.append({"kind": ot, "text": "".join(txt) if isinstance(txt, list) else txt})
                if "image/png" in out.get("data", {}):
                    outputs.append({"kind": "figure", "note": "image output — golden the plotted ARRAYS "
                                                             "from the cell source, not the pixels"})
            elif ot == "error":
                n_error_cells += 1
                outputs.append({"kind": "error", "ename": out.get("ename")})
        cells.append({
            "cell_index": i,
            "execution_count": ec,
            "source": "".join(cell.get("source", [])),
            "outputs": outputs,
        })
    # Strict linearity: counts must be consecutive 1..N. Gaps (1,2,4,7) prove
    # cells were re-run/deleted elsewhere = hidden state; monotonic-with-gaps
    # is NOT clean. Unexecuted cells void the check entirely.
    linear = (
        bool(exec_counts)
        and n_unexecuted == 0
        and exec_counts == list(range(1, len(exec_counts) + 1))
    )
    ks = nb.get("metadata", {}).get("kernelspec", {})
    li = nb.get("metadata", {}).get("language_info", {})
    return {
        "notebook": str(nb_path),
        "linear_execution": linear,
        "n_code_cells": len(cells),
        "n_unexecuted_cells": n_unexecuted,
        "n_error_cells": n_error_cells,
        # provenance: the env the goldens came from — compare against the app
        # env before trusting exact-value parity (pandas major drift changes numbers)
        "kernel": {"name": ks.get("name"), "display_name": ks.get("display_name"),
                   "python_version": li.get("version")},
        "cells": cells,
    }


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(1)
    goldens = harvest(sys.argv[1])
    Path(sys.argv[2]).write_text(json.dumps(goldens, indent=1), encoding="utf-8")
    # ASCII-only in print paths: Windows consoles default to legacy codepages
    # (cp949 etc.) and die on em-dashes/arrows (catalogue: Windows env notes).
    warns = []
    if not goldens["linear_execution"]:
        warns.append("execution_counts not consecutive 1..N - re-execute before trusting goldens")
    if goldens["n_unexecuted_cells"]:
        warns.append(f"{goldens['n_unexecuted_cells']} code cells never executed")
    if goldens["n_error_cells"]:
        warns.append(f"{goldens['n_error_cells']} cells contain ERROR outputs")
    flag = ("  ** WARNING: " + "; ".join(warns) + " **") if warns else ""
    print(f"{goldens['n_code_cells']} code cells -> {sys.argv[2]}{flag}")


if __name__ == "__main__":
    main()
