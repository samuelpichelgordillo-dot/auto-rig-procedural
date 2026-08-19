"""Módulo 1 — tests del pipeline de esqueletización sobre los 3 samples.

Cubre lo ya verificado manualmente en las sesiones de desarrollo (ver
CLAUDE.md): tras el pipeline completo (extract -> densify -> merge ->
root -> punto fijo collapse/RDP -> hierarchy) sobre cow/biped/bat, el
resultado es un único árbol conexo y sin ciclos, con raíz no trivial y
sin aristas por debajo del umbral de longitud mínima.
"""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path

import networkx as nx
import pytest

from backend.app.skeletonization import build_skeleton_tree

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"

_SHORT_EDGE_THRESHOLD_PCT = 0.005

# Nº de nodos finales de la última ejecución verificada manualmente (ver
# CLAUDE.md, checkpoint del Módulo 1). ±20% como rango de tolerancia: basta
# para detectar una regresión real sin ser frágil ante variaciones menores
# de skeletor/parámetros entre entornos.
_EXPECTED_FINAL_NODES = {
    "cow_unrigged.glb": 28,
    "biped_unrigged.glb": 182,
    "bat_unrigged.glb": 30,
}

_MAX_CONVERGENCE_ITERS = 5


def _bbox_diagonal(graph: nx.Graph) -> float:
    positions = [graph.nodes[n]["pos"] for n in graph.nodes]
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    return math.dist((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))


@pytest.fixture(params=sorted(_EXPECTED_FINAL_NODES), scope="module")
def pipeline_result(request):
    mesh_name = request.param
    tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / mesh_name))
    short_threshold = _SHORT_EDGE_THRESHOLD_PCT * _bbox_diagonal(tree)
    return mesh_name, tree, root, hierarchy, short_threshold


def test_pipeline_produces_single_connected_tree(pipeline_result):
    _, tree, _, _, _ = pipeline_result
    assert nx.number_connected_components(tree) == 1


def test_pipeline_produces_acyclic_tree(pipeline_result):
    _, tree, _, _, _ = pipeline_result
    assert nx.is_forest(tree)


def test_root_has_degree_at_least_three(pipeline_result):
    _, tree, root, _, _ = pipeline_result
    assert tree.degree[root] >= 3


def test_no_edges_below_minimum_length(pipeline_result):
    mesh_name, tree, _, hierarchy, short_threshold = pipeline_result
    short_edges = []
    for child, parent in hierarchy.items():
        if parent is None:
            continue
        length = math.dist(tree.nodes[parent]["pos"], tree.nodes[child]["pos"])
        if length < short_threshold:
            short_edges.append((parent, child, length))

    assert not short_edges, (
        f"{mesh_name}: {len(short_edges)} aristas por debajo del umbral "
        f"{short_threshold:.6f}: {short_edges}"
    )


def test_final_node_count_within_expected_range(pipeline_result):
    mesh_name, tree, _, _, _ = pipeline_result
    expected = _EXPECTED_FINAL_NODES[mesh_name]
    low, high = expected * 0.8, expected * 1.2
    n_nodes = tree.number_of_nodes()
    assert low <= n_nodes <= high, (
        f"{mesh_name}: {n_nodes} nodos finales, fuera del rango esperado "
        f"[{low:.0f}, {high:.0f}] (referencia: {expected})"
    )


@pytest.mark.parametrize("mesh_name", sorted(_EXPECTED_FINAL_NODES))
def test_converges_within_few_iterations(mesh_name, caplog):
    """build_skeleton_tree no expone el nº de rondas del punto fijo en su
    valor de retorno (firma deliberadamente simple) — lo registra vía
    ``logging``, así que este test lo lee de ahí en vez de cambiar la API
    pública solo para poder probarlo.
    """
    with caplog.at_level(logging.INFO, logger="backend.app.skeletonization"):
        build_skeleton_tree(str(_SAMPLES_DIR / mesh_name))

    match = None
    for record in caplog.records:
        found = re.search(r"convergió en (\d+) ronda", record.getMessage())
        if found:
            match = found
    assert match is not None, (
        f"{mesh_name}: no se encontró el mensaje de convergencia en los logs"
    )

    iterations = int(match.group(1))
    assert 1 <= iterations <= _MAX_CONVERGENCE_ITERS, (
        f"{mesh_name}: convergió en {iterations} rondas, "
        f"fuera del límite esperado ({_MAX_CONVERGENCE_ITERS})"
    )
