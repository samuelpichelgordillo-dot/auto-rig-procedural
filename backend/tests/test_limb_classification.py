"""Módulo 3 — clasificación de extremidades tipo "pata de apoyo".

Verifica ``classify_support_limbs`` contra lo ya sabido por inspección
manual en checkpoints anteriores (Módulo 1/2): cow es un cuadrúpedo (4
patas), biped es bípedo (2 piernas, brazos en T-pose NO deben contar) y
bat tiene patas traseras pequeñas (1-2, alas NO deben contar).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.limb_classification import classify_support_limbs
from backend.app.skeletonization import build_skeleton_tree

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"

# (nº de patas esperado, mínimo, máximo) — ver CLAUDE.md para el
# razonamiento completo por modelo.
_EXPECTED_LIMB_COUNT = {
    "cow_unrigged.glb": (4, 4),
    "biped_unrigged.glb": (2, 2),
    "bat_unrigged.glb": (1, 2),
}


@pytest.fixture(scope="module")
def skeleton_by_model():
    return {
        filename: build_skeleton_tree(str(_SAMPLES_DIR / filename))
        for filename in _EXPECTED_LIMB_COUNT
    }


@pytest.mark.parametrize("filename", list(_EXPECTED_LIMB_COUNT))
def test_limb_count_matches_known_anatomy(skeleton_by_model, filename):
    tree, root, hierarchy = skeleton_by_model[filename]
    limbs = classify_support_limbs(tree, root, hierarchy)

    min_expected, max_expected = _EXPECTED_LIMB_COUNT[filename]
    assert min_expected <= len(limbs) <= max_expected, (
        f"{filename}: {len(limbs)} patas detectadas, se esperaban entre "
        f"{min_expected} y {max_expected}"
    )


def test_every_limb_chain_root_is_a_real_tree_node(skeleton_by_model):
    """Regresión básica de forma: chain_root y foot_leaf deben ser nodos
    reales del árbol, y foot_leaf debe estar entre ground_leaves."""
    for filename, (tree, root, hierarchy) in skeleton_by_model.items():
        limbs = classify_support_limbs(tree, root, hierarchy)
        for limb in limbs:
            assert limb.chain_root in tree.nodes, f"{filename}: chain_root inválido"
            assert limb.foot_leaf in tree.nodes, f"{filename}: foot_leaf inválido"
            assert limb.foot_leaf in limb.ground_leaves, (
                f"{filename}: foot_leaf debe estar en ground_leaves"
            )
            assert len(limb.ground_leaves) >= 1


def test_no_ground_leaf_assigned_to_two_limbs(skeleton_by_model):
    """Cada hoja de suelo debe pertenecer a exactamente una pata (la
    agrupación no debe solapar)."""
    for filename, (tree, root, hierarchy) in skeleton_by_model.items():
        limbs = classify_support_limbs(tree, root, hierarchy)
        seen: set[int] = set()
        for limb in limbs:
            for leaf in limb.ground_leaves:
                assert leaf not in seen, f"{filename}: hoja {leaf} en más de una pata"
                seen.add(leaf)


def test_biped_arms_not_classified_as_limbs(skeleton_by_model):
    """Chequeo explícito del criterio de exclusión pedido: en biped (en
    T-pose), ninguna hoja de mano/dedo (altura muy por encima del suelo)
    debe aparecer como ``ground_leaves`` de ninguna pata — el criterio
    geométrico (altura cerca del Y mínimo global) debe excluir los brazos
    sin necesidad de ningún caso especial por nombre de hueso. `chain_root`
    en cambio SÍ se espera a media altura (es la cadera/hombro, no el
    pie) — no se comprueba aquí."""
    tree, root, hierarchy = skeleton_by_model["biped_unrigged.glb"]
    limbs = classify_support_limbs(tree, root, hierarchy)

    ys = [tree.nodes[n]["pos"][1] for n in tree.nodes]
    y_min = min(ys)
    y_range = max(ys) - y_min

    for limb in limbs:
        for leaf in limb.ground_leaves:
            rel_height = (tree.nodes[leaf]["pos"][1] - y_min) / y_range
            assert rel_height < 0.1, (
                f"biped: hoja {leaf} de una pata está a rel={rel_height:.3f} "
                "de altura — demasiado alto para ser un pie, probablemente "
                "una mano/dedo mal clasificado"
            )
