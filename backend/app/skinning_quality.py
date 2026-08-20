"""Lectura y análisis de datos de skinning (Módulo 2) directamente sobre un
GLB ya exportado, en Python puro (numpy + pygltflib) — sin Blender. Los
GLB de `samples/_debug/{cow,biped,bat}_rigged.glb` ya contienen Armature +
auto-weight generados por `backend/scripts/build_armature.py`; este módulo
solo los lee e inspecciona.

Convenciones de glTF 2.0 asumidas (válidas para los 3 samples y para
cualquier GLB exportado por Blender con el mismo pipeline):

  - Un único `skin` compartido por todos los nodos-malla del modelo (varios
    nodos pueden usar el mismo `skin`, cada uno con su propia malla y su
    propia transformación de nodo — p.ej. biped tiene 3 nodos-malla:
    Eyebrows/Eyes/SuperHero_Male, todos con `skin=0`).
  - Cada nodo-joint usa TRS (translation/rotation/scale), no `matrix`
    directo — se admite `matrix` como alternativa por robustez, pero no lo
    ejercitan estos samples.
  - Cuaterniones en orden glTF `[x, y, z, w]`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pygltflib

_COMPONENT_TYPE_TO_DTYPE = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}
_TYPE_TO_NUM_COMPONENTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT4": 16,
}


def _read_accessor(gltf: pygltflib.GLTF2, blob: bytes, accessor_index: int) -> np.ndarray:
    accessor = gltf.accessors[accessor_index]
    dtype = _COMPONENT_TYPE_TO_DTYPE[accessor.componentType]
    num_components = _TYPE_TO_NUM_COMPONENTS[accessor.type]
    buffer_view = gltf.bufferViews[accessor.bufferView]
    base_offset = (buffer_view.byteOffset or 0) + (accessor.byteOffset or 0)
    component_size = np.dtype(dtype).itemsize
    element_size = component_size * num_components
    stride = buffer_view.byteStride or element_size
    count = accessor.count

    if stride == element_size:
        flat = np.frombuffer(
            blob, dtype=dtype, count=count * num_components, offset=base_offset
        )
        data = flat.reshape(count, num_components)
    else:
        data = np.empty((count, num_components), dtype=dtype)
        for i in range(count):
            start = base_offset + i * stride
            data[i] = np.frombuffer(blob, dtype=dtype, count=num_components, offset=start)

    if accessor.type == "MAT4":
        # glTF almacena matrices column-major (16 floats: columna0..columna3);
        # reshape (count,4,4) da [columna][fila], transponer da [fila][columna].
        return data.reshape(count, 4, 4).transpose(0, 2, 1).astype(np.float64)
    if num_components == 1:
        return data[:, 0]
    return data.astype(np.float64) if dtype == np.float32 else data


def _quat_to_matrix3(quat: np.ndarray) -> np.ndarray:
    x, y, z, w = quat
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def quat_multiply(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
    """Producto de Hamilton q1*q2, cuaterniones en orden [x,y,z,w]."""
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return np.array(
        [
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        ],
        dtype=np.float64,
    )


def axis_angle_to_quat(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / np.linalg.norm(axis)
    half = angle_rad / 2.0
    return np.array([*(axis * np.sin(half)), np.cos(half)], dtype=np.float64)


def quat_conjugate(quat: np.ndarray) -> np.ndarray:
    """Inverso de un cuaternión unitario (conjugado): invierte el sentido
    de la rotación. Cuaterniones en orden [x,y,z,w]."""
    x, y, z, w = quat
    return np.array([-x, -y, -z, w], dtype=np.float64)


def matrix3_to_quat(rotation_matrix: np.ndarray) -> np.ndarray:
    """Convierte una matriz de rotación 3x3 a cuaternión [x,y,z,w]. Inversa
    de `_quat_to_matrix3` — algoritmo estándar por casos según la traza
    (Shepperd), para evitar división por un término casi nulo cuando la
    traza es negativa."""
    m = rotation_matrix
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = 0.5 / math.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (m[2, 1] - m[1, 2]) * s
        y = (m[0, 2] - m[2, 0]) * s
        z = (m[1, 0] - m[0, 1]) * s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = 2.0 * math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = 2.0 * math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    quat = np.array([x, y, z, w], dtype=np.float64)
    return quat / np.linalg.norm(quat)


def trs_to_matrix(
    translation: np.ndarray, rotation_quat: np.ndarray, scale: np.ndarray
) -> np.ndarray:
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = _quat_to_matrix3(rotation_quat) * scale[np.newaxis, :]
    matrix[:3, 3] = translation
    return matrix


_DEFAULT_TRANSLATION = np.zeros(3, dtype=np.float64)
_DEFAULT_ROTATION = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)
_DEFAULT_SCALE = np.ones(3, dtype=np.float64)


@dataclass
class NodeTRS:
    translation: np.ndarray
    rotation: np.ndarray
    scale: np.ndarray

    def to_matrix(self) -> np.ndarray:
        return trs_to_matrix(self.translation, self.rotation, self.scale)


def _node_trs(node: pygltflib.Node) -> NodeTRS:
    if node.matrix is not None:
        raise NotImplementedError(
            "Nodo con 'matrix' directo en vez de TRS no soportado — no aparece en "
            "los samples actuales (todos usan TRS)."
        )
    translation = (
        np.array(node.translation, dtype=np.float64)
        if node.translation is not None
        else _DEFAULT_TRANSLATION.copy()
    )
    rotation = (
        np.array(node.rotation, dtype=np.float64)
        if node.rotation is not None
        else _DEFAULT_ROTATION.copy()
    )
    scale = (
        np.array(node.scale, dtype=np.float64)
        if node.scale is not None
        else _DEFAULT_SCALE.copy()
    )
    return NodeTRS(translation, rotation, scale)


@dataclass
class Primitive:
    mesh_node_index: int
    positions: np.ndarray  # (N, 3) float64, espacio local del nodo-malla
    joints: np.ndarray  # (N, 4) int, índices de JOINT SLOT (0..J-1), no de nodo
    weights: np.ndarray  # (N, 4) float64
    triangles: np.ndarray  # (M, 3) int, índices de vértice locales a esta primitiva


@dataclass
class SkinData:
    primitives: list[Primitive]
    joint_node_indices: list[int]  # slot -> índice de nodo glTF
    inverse_bind_matrices: np.ndarray  # (J, 4, 4)
    node_trs: dict[int, NodeTRS]  # bind pose original, por nodo
    node_children: dict[int, list[int]]
    node_parent: dict[int, "int | None"]
    node_name: dict[int, str]
    root_node_index: int
    mesh_node_global_bind: dict[int, np.ndarray] = field(default_factory=dict)


def compute_global_matrices(
    root_node_index: int,
    node_children: dict[int, list[int]],
    local_matrix_of: dict[int, np.ndarray],
) -> dict[int, np.ndarray]:
    globals_: dict[int, np.ndarray] = {}

    def visit(node_index: int, parent_global: np.ndarray) -> None:
        local = local_matrix_of[node_index]
        world = parent_global @ local
        globals_[node_index] = world
        for child in node_children.get(node_index, []):
            visit(child, world)

    visit(root_node_index, np.eye(4, dtype=np.float64))
    return globals_


def read_skin_data(glb_path: str) -> SkinData:
    gltf = pygltflib.GLTF2().load(glb_path)
    blob = gltf.binary_blob()

    if len(gltf.skins) != 1:
        raise NotImplementedError(
            f"{glb_path}: se esperaba exactamente 1 skin, hay {len(gltf.skins)}"
        )
    skin = gltf.skins[0]

    node_children: dict[int, list[int]] = {
        i: list(n.children) for i, n in enumerate(gltf.nodes)
    }
    node_parent: dict[int, "int | None"] = {i: None for i in range(len(gltf.nodes))}
    for i, children in node_children.items():
        for c in children:
            node_parent[c] = i
    node_name = {i: (n.name or f"node_{i}") for i, n in enumerate(gltf.nodes)}
    node_trs = {i: _node_trs(n) for i, n in enumerate(gltf.nodes)}

    scene = gltf.scenes[gltf.scene or 0]
    if len(scene.nodes) != 1:
        raise NotImplementedError(
            f"{glb_path}: se esperaba 1 nodo raíz de escena, hay {len(scene.nodes)}"
        )
    root_node_index = scene.nodes[0]

    local_matrix_of = {i: trs.to_matrix() for i, trs in node_trs.items()}
    bind_globals = compute_global_matrices(root_node_index, node_children, local_matrix_of)

    inverse_bind_matrices = _read_accessor(gltf, blob, skin.inverseBindMatrices)

    mesh_node_indices = [i for i, n in enumerate(gltf.nodes) if n.mesh is not None]
    primitives: list[Primitive] = []
    mesh_node_global_bind: dict[int, np.ndarray] = {}
    for mesh_node_index in mesh_node_indices:
        node = gltf.nodes[mesh_node_index]
        mesh_node_global_bind[mesh_node_index] = bind_globals[mesh_node_index]
        mesh = gltf.meshes[node.mesh]
        for prim in mesh.primitives:
            if prim.mode not in (None, 4):  # 4 = TRIANGLES
                continue
            positions = _read_accessor(gltf, blob, prim.attributes.POSITION)
            joints_raw = _read_accessor(gltf, blob, prim.attributes.JOINTS_0)
            weights = _read_accessor(gltf, blob, prim.attributes.WEIGHTS_0)
            indices = _read_accessor(gltf, blob, prim.indices)
            triangles = indices.reshape(-1, 3).astype(np.int64)
            primitives.append(
                Primitive(
                    mesh_node_index=mesh_node_index,
                    positions=positions,
                    joints=joints_raw.astype(np.int64),
                    weights=weights,
                    triangles=triangles,
                )
            )

    return SkinData(
        primitives=primitives,
        joint_node_indices=list(skin.joints),
        inverse_bind_matrices=inverse_bind_matrices,
        node_trs=node_trs,
        node_children=node_children,
        node_parent=node_parent,
        node_name=node_name,
        root_node_index=root_node_index,
        mesh_node_global_bind=mesh_node_global_bind,
    )


def weight_smoothness_metric(skin_data: SkinData) -> np.ndarray:
    """Distancia L1 entre los vectores de peso completos (dispersos sobre
    TODOS los joints del skin, no solo los 4 slots) de cada par de vértices
    adyacentes en la triangulación. Rango [0, 2]: 0 = pesos idénticos,
    2 = completamente disjuntos. Devuelve el array completo de distancias
    (una por arista, agregado sobre todas las primitivas), no solo un
    resumen — para poder fijar un umbral con criterio a partir de la
    distribución real.
    """
    num_joints = len(skin_data.joint_node_indices)
    all_distances: list[np.ndarray] = []

    for prim in skin_data.primitives:
        n = prim.positions.shape[0]
        dense_weights = np.zeros((n, num_joints), dtype=np.float64)
        rows = np.repeat(np.arange(n), 4)
        cols = prim.joints.reshape(-1)
        vals = prim.weights.reshape(-1)
        np.add.at(dense_weights, (rows, cols), vals)

        edges: set[tuple[int, int]] = set()
        for a, b, c in prim.triangles:
            edges.add((min(a, b), max(a, b)))
            edges.add((min(b, c), max(b, c)))
            edges.add((min(a, c), max(a, c)))
        if not edges:
            continue
        edge_array = np.array(sorted(edges), dtype=np.int64)
        diff = dense_weights[edge_array[:, 0]] - dense_weights[edge_array[:, 1]]
        l1 = np.abs(diff).sum(axis=1)
        all_distances.append(l1)

    if not all_distances:
        return np.array([], dtype=np.float64)
    return np.concatenate(all_distances)


def apply_bone_rotation(
    skin_data: SkinData, joint_name: str, rotation_quaternion: np.ndarray
) -> list[np.ndarray]:
    """Aplica una rotación extra (cuaternión [x,y,z,w], espacio local del
    hueso) al hueso `joint_name`, compuesta DESPUÉS de su rotación de bind
    pose (rota el hueso, y con él toda su subjerarquía, sobre su propia
    orientación de reposo). Devuelve la lista de arrays de posiciones
    deformadas, una por primitiva, en el mismo orden que `skin_data.primitives`.

    Usa linear blend skinning:
        v' = Σ_i peso_i · (invMeshGlobal · jointGlobal_i · invBindMatrix_i) · v

    jointGlobal_i se recalcula recorriendo la jerarquía completa desde la
    raíz con la rotación del hueso objetivo ya aplicada, así que cualquier
    hueso descendiente hereda correctamente la nueva transformación de su
    padre.
    """
    target_node = None
    for node_index, name in skin_data.node_name.items():
        if name == joint_name:
            target_node = node_index
            break
    if target_node is None:
        raise ValueError(f"Hueso '{joint_name}' no encontrado")
    if target_node not in skin_data.joint_node_indices:
        raise ValueError(f"'{joint_name}' no es un joint del skin")

    local_matrix_of: dict[int, np.ndarray] = {}
    for node_index, trs in skin_data.node_trs.items():
        if node_index == target_node:
            new_rotation = quat_multiply(trs.rotation, rotation_quaternion)
            local_matrix_of[node_index] = trs_to_matrix(
                trs.translation, new_rotation, trs.scale
            )
        else:
            local_matrix_of[node_index] = trs.to_matrix()

    globals_ = compute_global_matrices(
        skin_data.root_node_index, skin_data.node_children, local_matrix_of
    )

    joint_globals = np.stack(
        [globals_[node_index] for node_index in skin_data.joint_node_indices]
    )  # (J, 4, 4)
    skin_matrices = np.einsum(
        "jab,jbc->jac", joint_globals, skin_data.inverse_bind_matrices
    )  # (J, 4, 4)

    deformed: list[np.ndarray] = []
    for prim in skin_data.primitives:
        mesh_global = skin_data.mesh_node_global_bind[prim.mesh_node_index]
        inv_mesh_global = np.linalg.inv(mesh_global)
        local_skin_matrices = np.einsum("ab,jbc->jac", inv_mesh_global, skin_matrices)

        n = prim.positions.shape[0]
        v_h = np.concatenate([prim.positions, np.ones((n, 1))], axis=1)  # (N, 4)

        result = np.zeros((n, 4), dtype=np.float64)
        for slot in range(4):
            slot_matrices = local_skin_matrices[prim.joints[:, slot]]  # (N, 4, 4)
            transformed = np.einsum("nab,nb->na", slot_matrices, v_h)
            result += prim.weights[:, slot : slot + 1] * transformed
        deformed.append(result[:, :3])

    return deformed


def verify_identity_rotation_reproduces_bind_pose(
    skin_data: SkinData, tolerance: float = 1e-5
) -> float:
    """Auto-chequeo obligatorio antes de usar `apply_bone_rotation` para
    cualquier otra cosa: una rotación de cuaternión identidad sobre
    CUALQUIER hueso debe reproducir exactamente las posiciones de bind
    pose (jointGlobal_bind · inverseBindMatrix ya es, por definición, la
    identidad para cada joint). Si esto falla, el bug está en la
    composición jerárquica de matrices globales o en la lectura de
    inverseBindMatrices — no en la rotación en sí. Devuelve el error
    máximo observado; lanza AssertionError si supera `tolerance`.
    """
    joint_name = skin_data.node_name[skin_data.joint_node_indices[0]]
    identity_quat = np.array([0.0, 0.0, 0.0, 1.0])
    deformed = apply_bone_rotation(skin_data, joint_name, identity_quat)
    max_error = 0.0
    for prim, deformed_positions in zip(skin_data.primitives, deformed):
        max_error = max(max_error, float(np.abs(deformed_positions - prim.positions).max()))
    if max_error >= tolerance:
        raise AssertionError(
            f"Rotación identidad no reproduce bind pose: error máximo {max_error} "
            f">= tolerancia {tolerance}. Bug en composición jerárquica de matrices."
        )
    return max_error
