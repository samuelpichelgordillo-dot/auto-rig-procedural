"""Depuración visual (matplotlib, sin Blender) de
`appendage_classification.classify_appendages`: dibuja el esqueleto
completo de un modelo (aristas del árbol de `build_skeleton_tree`),
coloreando las cadenas clasificadas como dedos/cola/orejas cada una en
un color distinto, las patas de apoyo en otro, y el resto en gris —
para comprobar a ojo que lo coloreado coincide con lo que un humano
llamaría dedos/cola/orejas en cada modelo.

Utilidad de un solo uso para nuestra propia inspección — no forma parte
de los tests automatizados (`backend/tests/`).

Uso:
    python backend/scripts/_plot_appendage_debug.py <modelo> <salida.png>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backend.app.appendage_classification import classify_appendages, limb_chain_nodes
from backend.app.gait_cycle import detect_stride_direction
from backend.app.limb_classification import classify_support_limbs
from backend.app.skeletonization import build_skeleton_tree

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"

_CATEGORY_COLORS = {
    "ears": "tab:red",
    "tail": "tab:green",
    "fingers": "tab:blue",
}
_LIMB_COLOR = "tab:orange"
_OTHER_COLOR = "0.75"


def main() -> None:
    if len(sys.argv) != 3:
        print("Uso: python _plot_appendage_debug.py <cow|biped|bat> <salida.png>")
        sys.exit(1)
    model, output_png = sys.argv[1], sys.argv[2]

    tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{model}_unrigged.glb"))
    limbs = classify_support_limbs(tree, root, hierarchy)
    direction = detect_stride_direction(limbs, tree)

    result = classify_appendages(tree, root, hierarchy, limbs)
    limb_nodes = limb_chain_nodes(limbs, hierarchy)

    node_category: dict[int, str] = {}
    for category, chains in result.items():
        for chain in chains:
            for node in chain:
                node_category[node] = category
    for node in limb_nodes:
        node_category.setdefault(node, "limb")

    def proj(node: int) -> tuple[float, float]:
        pos = np.array(tree.nodes[node]["pos"], dtype=np.float64)
        return float(np.dot(pos, direction)), float(pos[1])

    fig, ax = plt.subplots(1, 1, figsize=(7, 8))

    # Fondo: todas las aristas del árbol, coloreadas por la categoría del
    # nodo HIJO (así una arista que entra a una cadena de dedos/cola/
    # orejas se ve del color de esa categoría; el resto en gris).
    for u, v in tree.edges():
        child = v if hierarchy.get(v) == u else u
        color = _CATEGORY_COLORS.get(node_category.get(child), _OTHER_COLOR)
        if node_category.get(child) == "limb":
            color = _LIMB_COLOR
        xu, yu = proj(u)
        xv, yv = proj(v)
        ax.plot([xu, xv], [yu, yv], "-", color=color, linewidth=1.5, zorder=1)

    for node, category in node_category.items():
        color = _CATEGORY_COLORS.get(category, _LIMB_COLOR if category == "limb" else _OTHER_COLOR)
        x, y = proj(node)
        ax.plot(x, y, "o", color=color, markersize=4, zorder=2)

    handles = [
        plt.Line2D([0], [0], color=color, lw=2, label=label)
        for label, color in [
            ("orejas", _CATEGORY_COLORS["ears"]),
            ("cola", _CATEGORY_COLORS["tail"]),
            ("dedos", _CATEGORY_COLORS["fingers"]),
            ("pata de apoyo", _LIMB_COLOR),
            ("resto (sin clasificar)", _OTHER_COLOR),
        ]
    ]
    ax.legend(handles=handles, fontsize=8, loc="best")
    ax.set_xlabel("stride_direction (proyección horizontal)")
    ax.set_ylabel("Y (altura)")
    ax.set_aspect("equal")
    ax.set_title(f"{model}: clasificación de apéndices (orejas/cola/dedos) sobre el esqueleto completo")
    fig.tight_layout()
    fig.savefig(output_png, dpi=150)
    print(f"Guardado: {output_png}")
    for category, chains in result.items():
        print(f"  {category}: {len(chains)} cadena(s)")


if __name__ == "__main__":
    main()
