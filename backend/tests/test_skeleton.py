"""Módulo 1 — tests del pipeline de esqueletización sobre los 3 samples.

Cubre lo ya verificado manualmente en las sesiones de desarrollo (ver
CLAUDE.md): tras el pipeline completo (extract -> densify -> merge ->
root -> collapse -> RDP -> hierarchy) sobre cow/biped/bat, el resultado es
un único árbol conexo y sin ciclos, con raíz no trivial y sin aristas por
debajo del umbral de longitud mínima.
"""
from __future__ import annotations

import math
from pathlib import Path

import networkx as nx
import pytest

from backend.app.skeletonization import (
    build_hierarchy,
    collapse_short_edges,
    densify_long_edges,
    extract_skeleton_graph,
    merge_components,
    select_root,
    simplify_chains_rdp,
)

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"

# Mismos parámetros que backend/scripts/inspect_skeleton.py, para que estos
# tests describan exactamente el pipeline ya verificado a mano.
_LONG_EDGE_THRESHOLD_PCT = 0.10
_SHORT_EDGE_THRESHOLD_PCT = 0.005
_RDP_TOLERANCE_PCT = 0.005

# Nº de nodos finales de la última ejecución verificada manualmente (ver
# CLAUDE.md, checkpoint del Módulo 1). ±20% como rango de tolerancia: basta
# para detectar una regresión real sin ser frágil ante variaciones menores
# de skeletor/parámetros entre entornos.
_EXPECTED_FINAL_NODES = {
    "cow_unrigged.glb": 28,
    "biped_unrigged.glb": 183,
    "bat_unrigged.glb": 30,
}

# biped_unrigged.glb deja 1 arista residual por debajo del umbral de
# longitud mínima (padre=78, hijo=12, ~0.0042) que collapse_short_edges +
# simplify_chains_rdp no eliminan — detectado y documentado ya en el
# desarrollo del Módulo 1, pendiente de tratamiento específico (fusionar
# con el padre, descartar, etc. — no decidido). Se permite explícitamente
# aquí en vez de silenciar el test o esconder el caso: si aparece una
# segunda arista corta, o aparece en cow/bat, el test debe seguir fallando.
_KNOWN_SHORT_EDGE_EXCEPTIONS = {
    "cow_unrigged.glb": 0,
    "biped_unrigged.glb": 1,
    "bat_unrigged.glb": 0,
}


def _bbox_diagonal(graph: nx.Graph) -> float:
    positions = [graph.nodes[n]["pos"] for n in graph.nodes]
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    return math.dist((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))


def _run_pipeline(mesh_path: str):
    """Reproduce el pipeline completo del Módulo 1 (1.1 - 1.3)."""
    graph = extract_skeleton_graph(mesh_path)
    densified = densify_long_edges(
        graph, mesh_path, threshold_pct=_LONG_EDGE_THRESHOLD_PCT
    )
    merged = merge_components(densified)
    root = select_root(merged)

    diagonal = _bbox_diagonal(merged)
    short_threshold = _SHORT_EDGE_THRESHOLD_PCT * diagonal
    rdp_tolerance = _RDP_TOLERANCE_PCT * diagonal

    collapsed = collapse_short_edges(merged, root, short_threshold)
    simplified = simplify_chains_rdp(collapsed, root, rdp_tolerance)
    hierarchy = build_hierarchy(simplified, root)

    return simplified, root, hierarchy, short_threshold


@pytest.fixture(params=sorted(_EXPECTED_FINAL_NODES), scope="module")
def pipeline_result(request):
    mesh_name = request.param
    tree, root, hierarchy, short_threshold = _run_pipeline(
        str(_SAMPLES_DIR / mesh_name)
    )
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


def test_no_unexpected_edges_below_minimum_length(pipeline_result):
    mesh_name, tree, _, hierarchy, short_threshold = pipeline_result
    short_edges = []
    for child, parent in hierarchy.items():
        if parent is None:
            continue
        length = math.dist(tree.nodes[parent]["pos"], tree.nodes[child]["pos"])
        if length < short_threshold:
            short_edges.append((parent, child, length))

    allowed = _KNOWN_SHORT_EDGE_EXCEPTIONS[mesh_name]
    assert len(short_edges) <= allowed, (
        f"{mesh_name}: {len(short_edges)} aristas por debajo del umbral "
        f"{short_threshold:.6f} (se permiten {allowed} conocidas): {short_edges}"
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
