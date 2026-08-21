"""Módulo 3 — límites articulares: ejes de bisagra por articulación.

Nuevo módulo de test (`test_joint_limits.py`) para una pieza distinta
del proyecto: `joint_limits.compute_hinge_axes` calcula, para cada hueso
de una `LimbChain`, su eje de bisagra natural en bind pose. Nada de
límites de ángulo todavía — eso depende de tener primero ejes
verificados que tengan sentido.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from backend.app.ik_solver import chain_bone_names, name_to_node_index
from backend.app.joint_limits import (
    DEFAULT_DEGENERATE_ANGLE_THRESHOLD_DEG,
    compute_hinge_axes,
    hinge_axes_in_local_frame,
)
from backend.app.limb_classification import classify_support_limbs
from backend.app.skeletonization import build_skeleton_tree
from backend.app.skinning_quality import (
    axis_angle_to_quat,
    compute_global_matrices,
    quat_conjugate,
    quat_multiply,
    read_skin_data,
    trs_to_matrix,
)

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
_MODELS = ["cow", "biped", "bat"]


@pytest.fixture(scope="module")
def tree_and_limbs_by_model():
    data = {}
    for model in _MODELS:
        tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{model}_unrigged.glb"))
        limbs = classify_support_limbs(tree, root, hierarchy)
        data[model] = (tree, hierarchy, {limb.chain_root: limb for limb in limbs})
    return data


@pytest.fixture(scope="module")
def skin_data_by_model():
    return {
        model: read_skin_data(str(_SAMPLES_DIR / "_debug" / f"{model}_rigged.glb"))
        for model in _MODELS
    }


def _direct_hinge_axis(tree, hierarchy, bone_name: str) -> np.ndarray:
    """Recálculo independiente (fórmula directa, sin pasar por
    `compute_hinge_axes`) del eje de bisagra de un hueso NO degenerado."""
    _, parent_str, child_str = bone_name.split("_")
    head_node, tail_node = int(parent_str), int(child_str)
    grandparent_node = hierarchy[head_node]
    pos_head = np.array(tree.nodes[head_node]["pos"], dtype=np.float64)
    pos_tail = np.array(tree.nodes[tail_node]["pos"], dtype=np.float64)
    pos_grandparent = np.array(tree.nodes[grandparent_node]["pos"], dtype=np.float64)
    outgoing = pos_tail - pos_head
    incoming = pos_head - pos_grandparent
    axis = np.cross(incoming, outgoing)
    return axis / np.linalg.norm(axis)


# Huesos de cow con ángulo entrante/saliente cómodamente por encima del
# umbral de degeneración (>20°, bien lejos de los 10° de margen) —
# identificados inspeccionando los ángulos reales de cada hueso de la
# cadena antes de escribir este test (no elegidos a ciegas):
#   chain_root=31: bone_31_10 (107.5°), bone_4_31 (25.1°)
#   chain_root=3:  bone_3_29 (34.6°)
_COW_WELL_DEFINED_BONES = [
    (31, "bone_31_10"),
    (31, "bone_4_31"),
    (3, "bone_3_29"),
]


@pytest.mark.parametrize("chain_root,bone_name", _COW_WELL_DEFINED_BONES)
def test_hinge_axis_matches_direct_formula_for_well_defined_joints(
    tree_and_limbs_by_model, chain_root, bone_name
):
    tree, hierarchy, limbs_by_root = tree_and_limbs_by_model["cow"]
    limb = limbs_by_root[chain_root]

    computed = compute_hinge_axes(limb, hierarchy, tree)
    direct = _direct_hinge_axis(tree, hierarchy, bone_name)

    assert bone_name in computed
    np.testing.assert_allclose(computed[bone_name], direct, atol=1e-9)


@pytest.mark.parametrize("model,expected_excluded", [("cow", ["bone_2_27", "bone_2_3"]), ("bat", ["bone_13_17"])])
def test_hip_shoulder_pivot_excluded(tree_and_limbs_by_model, model, expected_excluded):
    """El hueso cuyo padre (P) es la raíz del propio esqueleto (GP =
    hierarchy[P] is None) no debe aparecer en el resultado — es la
    articulación más proximal (cadera/hombro), anatómicamente más "bola"
    que "bisagra"."""
    tree, hierarchy, limbs_by_root = tree_and_limbs_by_model[model]
    limbs = list(limbs_by_root.values())

    for limb in limbs:
        computed = compute_hinge_axes(limb, hierarchy, tree)
        for bone_name in chain_bone_names(limb, hierarchy):
            _, parent_str, _ = bone_name.split("_")
            grandparent = hierarchy[int(parent_str)]
            if grandparent is None:
                assert bone_name not in computed, (
                    f"{model}: {bone_name} tiene GP=None (pivote de cadera/"
                    "hombro pegado a la raíz) y no debería aparecer en el resultado"
                )

    # Confirma también, explícitamente, que los huesos esperados sí caen
    # en ese caso (no solo que "si caen, se excluyen" — que de verdad caigan).
    all_excluded = set()
    for limb in limbs:
        computed = compute_hinge_axes(limb, hierarchy, tree)
        for bone_name in chain_bone_names(limb, hierarchy):
            if bone_name not in computed:
                all_excluded.add(bone_name)
    for bone_name in expected_excluded:
        assert bone_name in all_excluded, f"{model}: se esperaba {bone_name} excluido"


def test_degenerate_joints_inherit_from_neighbor(tree_and_limbs_by_model):
    """Identifica los huesos degenerados de biped RE-CALCULANDO los
    ángulos reales aquí (no hardcodeados de memoria), y confirma que
    `compute_hinge_axes` los incluye en el resultado (heredaron un eje,
    no se omitieron) con un eje EXACTAMENTE igual al de algún vecino
    resuelto en la cadena."""
    tree, hierarchy, limbs_by_root = tree_and_limbs_by_model["biped"]
    limbs = list(limbs_by_root.values())

    degenerate_bones = []  # (chain_root, bone_name)
    resolved_bones = []  # (chain_root, bone_name)
    for limb in limbs:
        for bone_name in chain_bone_names(limb, hierarchy):
            _, parent_str, child_str = bone_name.split("_")
            head_node, tail_node = int(parent_str), int(child_str)
            grandparent_node = hierarchy[head_node]
            if grandparent_node is None:
                continue
            pos_head = np.array(tree.nodes[head_node]["pos"], dtype=np.float64)
            pos_tail = np.array(tree.nodes[tail_node]["pos"], dtype=np.float64)
            pos_gp = np.array(tree.nodes[grandparent_node]["pos"], dtype=np.float64)
            outgoing = pos_tail - pos_head
            incoming = pos_head - pos_gp
            cos_angle = np.clip(
                float(np.dot(incoming, outgoing))
                / (np.linalg.norm(incoming) * np.linalg.norm(outgoing)),
                -1.0, 1.0,
            )
            angle_deg = math.degrees(math.acos(cos_angle))
            if (
                angle_deg < DEFAULT_DEGENERATE_ANGLE_THRESHOLD_DEG
                or angle_deg > 180.0 - DEFAULT_DEGENERATE_ANGLE_THRESHOLD_DEG
            ):
                degenerate_bones.append((limb.chain_root, bone_name))
            else:
                resolved_bones.append((limb.chain_root, bone_name))

    assert degenerate_bones, "biped: se esperaban huesos degenerados (checkpoint 2026-08-21)"

    for chain_root, bone_name in degenerate_bones:
        limb = limbs_by_root[chain_root]
        computed = compute_hinge_axes(limb, hierarchy, tree)

        assert bone_name in computed, (
            f"biped: {bone_name} (degenerado, ángulo casi recto) debería "
            "haber heredado un eje, no ser omitido"
        )

        neighbor_axes = [
            computed[neighbor_bone_name]
            for neighbor_root, neighbor_bone_name in resolved_bones
            if neighbor_root == chain_root and neighbor_bone_name in computed
        ]
        matches_some_neighbor = any(
            np.allclose(computed[bone_name], axis, atol=1e-9) for axis in neighbor_axes
        )
        assert matches_some_neighbor, (
            f"biped: el eje heredado de {bone_name} no coincide exactamente "
            "con el de ningún hueso resuelto de su misma cadena"
        )


@pytest.mark.parametrize("model", _MODELS)
def test_all_returned_axes_are_unit_length(tree_and_limbs_by_model, model):
    tree, hierarchy, limbs_by_root = tree_and_limbs_by_model[model]
    for limb in limbs_by_root.values():
        computed = compute_hinge_axes(limb, hierarchy, tree)
        for bone_name, axis in computed.items():
            assert np.linalg.norm(axis) == pytest.approx(1.0), (
                f"{model}: eje de {bone_name} no tiene norma 1 ({np.linalg.norm(axis)})"
            )


# --- hinge_axes_in_local_frame ---


def _independent_bind_rotation_quat(skin_data, node_index) -> np.ndarray:
    """Recálculo independiente de la rotación GLOBAL de bind pose de un
    nodo: recorre a mano la cadena de padres desde `root_node_index`
    hasta `node_index`, componiendo cuaterniones con `quat_multiply` —
    NO usa `compute_global_matrices` (esa es la ruta que usa la función
    bajo prueba)."""
    chain = [node_index]
    node = node_index
    while node != skin_data.root_node_index:
        node = skin_data.node_parent[node]
        chain.append(node)
    chain.reverse()  # root -> ... -> node_index

    quat = skin_data.node_trs[chain[0]].rotation
    for node in chain[1:]:
        quat = quat_multiply(quat, skin_data.node_trs[node].rotation)
    return quat


def _rotate_vector_by_quat(vector: np.ndarray, quat: np.ndarray) -> np.ndarray:
    """v' = q · (v,0) · conj(q)."""
    v_quat = np.array([vector[0], vector[1], vector[2], 0.0])
    rotated = quat_multiply(quat_multiply(quat, v_quat), quat_conjugate(quat))
    return rotated[:3]


# Mismos huesos bien definidos de cow ya usados en
# test_hinge_axis_matches_direct_formula_for_well_defined_joints.
_COW_WELL_DEFINED_BONES_2 = [
    (31, "bone_31_10"),
    (31, "bone_4_31"),
    (3, "bone_3_29"),
]


@pytest.mark.parametrize("chain_root,bone_name", _COW_WELL_DEFINED_BONES_2)
def test_local_axis_reconstructs_world_axis_via_independent_global_rotation(
    tree_and_limbs_by_model, skin_data_by_model, chain_root, bone_name
):
    """Confirma que `hinge_axes_in_local_frame` no cogió el nodo
    equivocado como "padre" ni invirtió mal la rotación: recalcula la
    rotación global del padre por una ruta genuinamente distinta
    (composición manual de cuaterniones, no `compute_global_matrices`) y
    comprueba que rotar el eje LOCAL devuelto por esa rotación
    reconstruye el mismo `world_axis` que `parent_rotation @ local_axis`
    (con el `parent_rotation` que sí usa la función bajo prueba)."""
    tree, hierarchy, limbs_by_root = tree_and_limbs_by_model["cow"]
    skin_data = skin_data_by_model["cow"]
    limb = limbs_by_root[chain_root]

    world_axes = compute_hinge_axes(limb, hierarchy, tree)
    local_axes = hinge_axes_in_local_frame(skin_data, world_axes)
    assert bone_name in local_axes

    name_to_index = name_to_node_index(skin_data)
    node_index = name_to_index[bone_name]
    parent_index = skin_data.node_parent[node_index]

    # parent_rotation "oficial", por la misma ruta que usa la función bajo prueba.
    local_matrix_of = {
        idx: trs_to_matrix(trs.translation, trs.rotation, trs.scale)
        for idx, trs in skin_data.node_trs.items()
    }
    bind_globals = compute_global_matrices(
        skin_data.root_node_index, skin_data.node_children, local_matrix_of
    )
    parent_rotation = bind_globals[parent_index][:3, :3]
    expected = parent_rotation @ local_axes[bone_name]

    # Ruta independiente: cuaternión compuesto a mano, rotación de vector
    # vía quat_multiply/quat_conjugate, sin pasar por compute_global_matrices
    # ni por ninguna matriz.
    independent_parent_quat = _independent_bind_rotation_quat(skin_data, parent_index)
    independent_result = _rotate_vector_by_quat(local_axes[bone_name], independent_parent_quat)

    np.testing.assert_allclose(independent_result, expected, atol=1e-6)


@pytest.mark.parametrize("model", _MODELS)
def test_local_axes_are_unit_length(tree_and_limbs_by_model, skin_data_by_model, model):
    tree, hierarchy, limbs_by_root = tree_and_limbs_by_model[model]
    skin_data = skin_data_by_model[model]
    for limb in limbs_by_root.values():
        world_axes = compute_hinge_axes(limb, hierarchy, tree)
        local_axes = hinge_axes_in_local_frame(skin_data, world_axes)
        for bone_name, axis in local_axes.items():
            assert np.linalg.norm(axis) == pytest.approx(1.0), (
                f"{model}: eje local de {bone_name} no tiene norma 1"
            )


_COW_COROTATION_TEST_BONES = [
    (31, "bone_31_10"),
    (3, "bone_3_29"),
]


@pytest.mark.parametrize("chain_root,bone_name", _COW_COROTATION_TEST_BONES)
def test_hinge_axis_co_rotates_with_ancestor_perturbation(
    tree_and_limbs_by_model, skin_data_by_model, chain_root, bone_name
):
    """La prueba MÁS importante de esta tarea: confirma que el eje local
    realmente sirve para recuperar la dirección de mundo válida en una
    pose DISTINTA de la bind pose, no solo en bind pose misma — que es
    exactamente lo que hará falta cuando `solve_ik_ccd` esté resolviendo
    otras articulaciones de la misma pata (tarea siguiente)."""
    tree, hierarchy, limbs_by_root = tree_and_limbs_by_model["cow"]
    skin_data = skin_data_by_model["cow"]
    limb = limbs_by_root[chain_root]

    world_axes = compute_hinge_axes(limb, hierarchy, tree)
    local_axes = hinge_axes_in_local_frame(skin_data, world_axes)

    # Rotación extra antepuesta en la RAÍZ del esqueleto entero — así toda
    # rotación global descendiente queda multiplicada por la misma
    # extra_rotation por la izquierda, sin ambigüedad de qué nodo perturbar.
    extra_rotation = axis_angle_to_quat(np.array([0.0, 1.0, 0.0]), math.radians(30))
    root_trs = skin_data.node_trs[skin_data.root_node_index]
    perturbed_root_local = quat_multiply(extra_rotation, root_trs.rotation)

    local_matrix_of = {
        idx: trs_to_matrix(trs.translation, trs.rotation, trs.scale)
        for idx, trs in skin_data.node_trs.items()
    }
    local_matrix_of[skin_data.root_node_index] = trs_to_matrix(
        root_trs.translation, perturbed_root_local, root_trs.scale
    )
    perturbed_globals = compute_global_matrices(
        skin_data.root_node_index, skin_data.node_children, local_matrix_of
    )

    name_to_index = name_to_node_index(skin_data)
    node_index = name_to_index[bone_name]
    parent_index = skin_data.node_parent[node_index]

    new_parent_rotation = perturbed_globals[parent_index][:3, :3]
    new_world_axis = new_parent_rotation @ local_axes[bone_name]

    # Esperado: rotar el world_axis ORIGINAL (antes de convertir a local)
    # por extra_rotation directamente, como rotación de vector — NO
    # reutiliza new_parent_rotation, sería circular.
    expected = _rotate_vector_by_quat(world_axes[bone_name], extra_rotation)

    np.testing.assert_allclose(new_world_axis, expected, atol=1e-6)
