"""Depuración visual (matplotlib, sin Blender) del estancamiento
direccional de CCD investigado en el checkpoint del Módulo 3
(2026-08-21, cow `chain_root=3`): para una pata dada, dibuja en 2D
(proyección sobre el plano `stride_direction`/Y) la cadena de huesos en
bind pose junto con los objetivos de las 30 fases del ciclo de marcha,
coloreados en verde si `solve_ik_ccd` converge y en rojo si no.

Utilidad de un solo uso para nuestra propia inspección — no forma parte
de los tests automatizados (`backend/tests/`).

Uso:
    python backend/scripts/_plot_leg_reach_debug.py <modelo> <chain_root> \\
        <salida.png> [--max-iterations N] [--raw-amplitude]

    --max-iterations N   Presupuesto de iteraciones de solve_ik_ccd (por
                          defecto, el DEFAULT_MAX_ITERATIONS actual del
                          solver — pasar 500 reproduce el comportamiento
                          "antes del fix" del checkpoint 2026-08-21).
    --raw-amplitude       Usa stride_amplitude_pct=0.3 sin pasar por
                          safe_stride_amplitude_pct (por defecto SÍ se
                          usa la amplitud segura, como hace el flujo
                          real).

Ejemplos (los que generaron las figuras del checkpoint 2026-08-21):
    # Antes del fix: presupuesto viejo (500), amplitud segura (no recorta
    # esta pata de todas formas, ver CLAUDE.md).
    python backend/scripts/_plot_leg_reach_debug.py cow 3 \\
        samples/_debug/cow_root3_before_fix.png --max-iterations 500

    # Después del fix: presupuesto actual (1000).
    python backend/scripts/_plot_leg_reach_debug.py cow 3 \\
        samples/_debug/cow_root3_after_fix.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backend.app.gait_cycle import (
    foot_target_at_phase,
    max_chain_bone_length,
    safe_stride_amplitude_pct,
)
from backend.app.ik_solver import DEFAULT_MAX_ITERATIONS, chain_bone_names, solve_ik_ccd
from backend.app.limb_classification import classify_support_limbs
from backend.app.skeletonization import build_skeleton_tree
from backend.app.skinning_quality import read_skin_data

_STRIDE_DIRECTION = np.array([0.0, 0.0, 1.0])
_NUM_PHASE_SAMPLES = 30
_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"


def _project(point: np.ndarray, chain_root_pos: np.ndarray, stride_direction: np.ndarray) -> tuple[float, float]:
    """Proyección 2D: eje X = componente a lo largo de `stride_direction`,
    eje Y = altura (Y), ambos relativos a `chain_root_pos` (el pivote más
    proximal de la pata, origen natural del plano)."""
    relative = np.asarray(point, dtype=np.float64) - chain_root_pos
    x = float(np.dot(relative, stride_direction))
    y = float(relative[1])
    return x, y


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=["cow", "biped", "bat"])
    parser.add_argument("chain_root", type=int)
    parser.add_argument("output_png")
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--raw-amplitude", action="store_true")
    args = parser.parse_args()

    tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{args.model}_unrigged.glb"))
    limbs = classify_support_limbs(tree, root, hierarchy)
    limbs_by_root = {limb.chain_root: limb for limb in limbs}
    if args.chain_root not in limbs_by_root:
        raise SystemExit(
            f"chain_root={args.chain_root} no es una pata de {args.model} "
            f"(patas disponibles: {sorted(limbs_by_root)})"
        )
    limb = limbs_by_root[args.chain_root]
    skin_data = read_skin_data(str(_SAMPLES_DIR / "_debug" / f"{args.model}_rigged.glb"))

    bind_foot = np.array(tree.nodes[limb.foot_leaf]["pos"], dtype=np.float64)
    chain_root_pos = np.array(tree.nodes[limb.chain_root]["pos"], dtype=np.float64)

    if args.raw_amplitude:
        amplitude = 0.3
    else:
        max_length = max_chain_bone_length(limb, hierarchy, tree)
        amplitude = safe_stride_amplitude_pct(bind_foot, chain_root_pos, max_length, _STRIDE_DIRECTION)

    # --- Cadena de huesos en bind pose (polilínea de chain_root a foot_leaf) ---
    chain_nodes = [args.chain_root]
    node = limb.foot_leaf
    path = [limb.foot_leaf]
    while node != args.chain_root:
        node = hierarchy[node]
        path.append(node)
    path.reverse()  # chain_root -> ... -> foot_leaf
    chain_points_2d = [_project(tree.nodes[n]["pos"], chain_root_pos, _STRIDE_DIRECTION) for n in path]

    fig, ax = plt.subplots(figsize=(8, 8))

    xs, ys = zip(*chain_points_2d)
    ax.plot(xs, ys, "o-", color="black", linewidth=2, markersize=6, label="cadena (bind pose)", zorder=3)
    for n, (x, y) in zip(path, chain_points_2d):
        ax.annotate(str(n), (x, y), textcoords="offset points", xytext=(6, 6), fontsize=8)

    # Círculo de alcance máximo (suma de longitudes de hueso) centrado en chain_root.
    max_length = max_chain_bone_length(limb, hierarchy, tree)
    theta = np.linspace(0, 2 * np.pi, 200)
    ax.plot(
        max_length * np.cos(theta), max_length * np.sin(theta),
        "--", color="gray", linewidth=1, label=f"alcance máximo ({max_length:.2f})", zorder=1,
    )

    # --- Objetivos de las 30 fases, coloreados por convergencia ---
    converged_pts, failed_pts = [], []
    for i in range(_NUM_PHASE_SAMPLES):
        phase = i / _NUM_PHASE_SAMPLES
        target = foot_target_at_phase(
            bind_foot, chain_root_pos, _STRIDE_DIRECTION, phase, stride_amplitude_pct=amplitude
        )
        result = solve_ik_ccd(
            skin_data, limb, hierarchy, bind_foot, target, max_iterations=args.max_iterations
        )
        point_2d = _project(target, chain_root_pos, _STRIDE_DIRECTION)
        if result.converged:
            converged_pts.append((phase, *point_2d, result.iterations_used))
        else:
            failed_pts.append((phase, *point_2d, result.iterations_used))
        print(
            f"phase={phase:.3f} iters={result.iterations_used} "
            f"err={result.final_error:.6f} conv={result.converged}"
        )

    if converged_pts:
        px = [p[1] for p in converged_pts]
        py = [p[2] for p in converged_pts]
        ax.scatter(px, py, color="green", s=60, label="converge", zorder=4)
    if failed_pts:
        px = [p[1] for p in failed_pts]
        py = [p[2] for p in failed_pts]
        ax.scatter(px, py, color="red", s=60, label="NO converge", zorder=5)
        for phase, x, y, iters in failed_pts:
            ax.annotate(
                f"phase={phase:.3f}\n{iters}it", (x, y),
                textcoords="offset points", xytext=(8, -12), fontsize=7, color="red",
            )

    ax.axhline(0, color="lightgray", linewidth=0.5, zorder=0)
    ax.axvline(0, color="lightgray", linewidth=0.5, zorder=0)
    ax.set_xlabel("componente a lo largo de stride_direction (relativo a chain_root)")
    ax.set_ylabel("altura Y (relativo a chain_root)")
    ax.set_title(
        f"{args.model} chain_root={args.chain_root} — amplitud={amplitude:.4f} "
        f"max_iterations={args.max_iterations}\n"
        f"{len(converged_pts)}/{_NUM_PHASE_SAMPLES} fases convergen"
    )
    ax.legend(loc="upper left", fontsize=8)
    ax.set_aspect("equal")

    fig.tight_layout()
    fig.savefig(args.output_png, dpi=150)
    print(f"Guardado: {args.output_png}")


if __name__ == "__main__":
    main()
