"""Módulo 4 — micro-movimientos: identificación de apéndices.

Cubre `appendage_classification.classify_appendages` sobre los 3
modelos: cow debe dar orejas (2 cadenas) y cola (1 cadena) no vacías;
biped debe dar al menos una mano en "fingers" (sin asumir cuántas); bat
debe dar cola no vacía y orejas VACÍAS (confirma que el filtro de
desplazamiento evitó clasificar las puntas de ala como orejas).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.appendage_classification import classify_appendages, limb_chain_nodes
from backend.app.limb_classification import classify_support_limbs
from backend.app.skeletonization import build_skeleton_tree

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
_MODELS = ["cow", "biped", "bat"]


@pytest.fixture(scope="module")
def tree_and_limbs_by_model():
    data = {}
    for model in _MODELS:
        tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{model}_unrigged.glb"))
        limbs = classify_support_limbs(tree, root, hierarchy)
        data[model] = (tree, root, hierarchy, limbs)
    return data


def test_cow_has_ears_and_tail(tree_and_limbs_by_model):
    tree, root, hierarchy, limbs = tree_and_limbs_by_model["cow"]
    result = classify_appendages(tree, root, hierarchy, limbs)

    assert len(result["ears"]) == 2, f"cow: se esperaban 2 cadenas de oreja, salió {result['ears']}"
    assert len(result["tail"]) == 1, f"cow: se esperaba 1 cadena de cola, salió {result['tail']}"

    # Las dos cadenas de oreja deben terminar en el mismo hub (misma
    # bifurcación bilateral) — verificado con datos reales antes de
    # escribir esta pieza: ambas terminan en la raíz del esqueleto (2).
    ear_hubs = {chain[-1] for chain in result["ears"]}
    assert len(ear_hubs) == 1, f"cow: las 2 orejas deberían compartir hub, salió {ear_hubs}"


def test_biped_has_at_least_one_hand(tree_and_limbs_by_model):
    """No se asume cuántas manos encuentra el heurístico (documentado en
    el propio módulo: la mano derecha de este biped concreto no se
    agrupa bajo un único hub por asimetría real del esqueleto) — solo
    que encuentra AL MENOS una."""
    tree, root, hierarchy, limbs = tree_and_limbs_by_model["biped"]
    result = classify_appendages(tree, root, hierarchy, limbs)

    assert len(result["fingers"]) >= 3, (
        f"biped: se esperaban al menos 3 cadenas de dedos (una mano real), "
        f"salió {result['fingers']}"
    )


def test_bat_has_tail_and_no_ears(tree_and_limbs_by_model):
    """Confirma que el filtro de desplazamiento (relativo al alcance de
    pata) evitó clasificar las puntas de ala de bat como orejas, pese a
    estar en posiciones aparentemente espejo."""
    tree, root, hierarchy, limbs = tree_and_limbs_by_model["bat"]
    result = classify_appendages(tree, root, hierarchy, limbs)

    assert len(result["tail"]) == 1, f"bat: se esperaba 1 cadena de cola, salió {result['tail']}"
    assert result["ears"] == [], f"bat: se esperaban 0 orejas (alas, no orejas), salió {result['ears']}"


@pytest.mark.parametrize("model", _MODELS)
def test_appendage_nodes_disjoint_from_limb_nodes(tree_and_limbs_by_model, model):
    """Ningún nodo clasificado como apéndice debe pertenecer también a
    una pata de apoyo — `classify_appendages` opera exclusivamente
    sobre el complemento de `limb_chain_nodes`."""
    tree, root, hierarchy, limbs = tree_and_limbs_by_model[model]
    limb_nodes = limb_chain_nodes(limbs, hierarchy)
    result = classify_appendages(tree, root, hierarchy, limbs)

    for category, chains in result.items():
        for chain in chains:
            for node in chain:
                assert node not in limb_nodes, (
                    f"{model}: nodo {node} de la categoría '{category}' "
                    "pertenece también a una pata de apoyo"
                )


@pytest.mark.parametrize("model", _MODELS)
def test_no_node_appears_in_two_categories(tree_and_limbs_by_model, model):
    tree, root, hierarchy, limbs = tree_and_limbs_by_model[model]
    result = classify_appendages(tree, root, hierarchy, limbs)

    seen: dict[int, str] = {}
    for category, chains in result.items():
        for chain in chains:
            leaf = chain[0]
            assert leaf not in seen, (
                f"{model}: la hoja {leaf} aparece tanto en '{seen[leaf]}' como en '{category}'"
            )
            seen[leaf] = category
