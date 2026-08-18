# CLAUDE.md — Auto-Rig & Animación Procedural para Criaturas 3D

Este archivo es la memoria central del proyecto. Léelo por completo al empezar
cada sesión. Después de completar y verificar cada módulo, actualiza la
sección "Estado actual" y el "Historial de checkpoints" antes de pasar al
siguiente módulo. No avances de módulo sin que su comando de verificación
haya pasado.

## Visión del proyecto

App capaz de tomar cualquier criatura 3D en formato GLB y:
1. Detectar automáticamente su esqueleto (máximo número de articulaciones
   identificables con coherencia, incluyendo micro-huesos: párpados, dedos,
   cola, orejas).
2. Generar el skinning (pesos de piel) de forma robusta.
3. Aplicar animación procedural básica (caminar, correr, poses como "asombro"),
   generada matemáticamente, no por clips pregrabados.
4. Añadir micro-movimientos (respiración, parpadeo, dedos, cola/orejas).
5. Generar micro-expresiones faciales.

Salida siempre en GLB estándar, para máxima compatibilidad (motores de juego,
vídeo, visores web, AR/VR).

## Arquitectura (stack) — no cambiar sin actualizar esta sección

- Backend: Python 3.11+, FastAPI.
- Motor de cómputo geométrico: Blender en modo headless (`bpy`), invocado como
  subproceso `blender --background --python script.py`. Blender nunca es
  visible al usuario final, es solo motor de cálculo.
- Formato de intercambio: GLB/glTF 2.0 en todo el pipeline.
- Frontend/visor de pruebas: Three.js (Vite), carga GLB por input de archivo,
  OrbitControls, AnimationMixer para previsualizar animaciones.
- Testing: `pytest` para el backend. Cada módulo debe incluir al menos un test
  automatizado que verifique su criterio de éxito, no solo inspección visual.

## Enfoque de auto-rigging

Heurística geométrica primero (esqueletización por contracción de malla +
clasificación topológica del grafo resultante), no ML. Motivo: determinista,
depurable, no requiere dataset etiquetado. ML queda como posible mejora en
fase de pulido, una vez tengamos casos reales fallidos con los que evaluar.

## Estado actual

- **Módulo actual:** 1 — Detección de esqueleto (siguiente a iniciar)
- **Estado:** Módulo 0 completado y verificado

## Roadmap por módulos

Cada módulo se da por completo únicamente cuando su comando de verificación
pasa sin errores. No se avanza al siguiente módulo antes de eso.

### Módulo 0 — Cimientos
- Objetivo: estructura de repo, backend arrancando, frontend cargando un GLB,
  script de inspección funcionando sobre Blender headless.
- Entregables: `backend/app/main.py` (health-check), `backend/scripts/inspect_glb.py`,
  `frontend/` (Vite + Three.js mínimo), `samples/` con README pidiendo modelos
  de prueba, `requirements.txt`.
- Verificación: `python backend/scripts/inspect_glb.py samples/<modelo>.glb`
  se ejecuta sin errores e imprime nº de vértices, huesos existentes,
  bounding box y nº de materiales. Además: `pytest backend/tests/test_setup.py`
  (test mínimo que confirma que Blender headless responde).

### Módulo 1 — Detección de esqueleto
- Objetivo: esqueletización de malla (contracción tipo Laplaciano) +
  clasificación topológica (raíz/columna, extremidades, hojas: dedos, cola,
  orejas) + generación del `Armature` en Blender con jerarquía correcta.
- Verificación: `pytest backend/tests/test_skeleton.py` sobre los 3 GLB de
  muestra (cuadrúpedo, bípedo, atípico) — comprueba nº de huesos razonable,
  jerarquía padre-hijo sin ciclos, y que la raíz esté cerca del centroide de
  masa. Validación visual adicional en el visor.

### Módulo 2 — Skinning
- Objetivo: auto-weighting por difusión de calor + post-proceso (máx. 4
  influencias/vértice, normalizado, suavizado).
- Verificación: `pytest backend/tests/test_skinning.py` — ningún vértice sin
  peso asignado, ninguna influencia negativa o > 1 tras normalizar, máx. 4
  huesos por vértice. Test de deformación: mover un hueso no debe dejar
  vértices "huérfanos" (distancia post-deformación dentro de un umbral).

### Módulo 3 — Animación procedural básica
- Objetivo: ciclos de marcha/carrera paramétricos (senoidales con desfase de
  fase por extremidad), IK simple (CCD/FABRIK) para contacto con el suelo,
  pose de "asombro" como ejemplo de pose dirigida.
- Verificación: `pytest backend/tests/test_locomotion.py` sobre los 3 modelos
  — el ciclo de marcha es periódico y estable, los pies/patas no atraviesan
  el plano del suelo más de un umbral tolerado.

### Módulo 4 — Micro-movimientos
- Objetivo: respiración, parpadeo, ruido de baja frecuencia en dedos/cola/orejas.
- Verificación: `pytest backend/tests/test_micromovements.py` — amplitud de
  los micro-movimientos dentro de rango (perceptible pero no rompe el ciclo
  principal), parpadeo con intervalo dentro de rango fisiológico razonable.

### Módulo 5 — Micro-expresiones faciales
- Objetivo: morph targets en zonas faciales detectadas (ojos, boca) o fallback
  por huesos (mandíbula, ojos, cejas).
- Verificación: al menos 3 expresiones (sorpresa, enfado, calma) generadas y
  exportadas correctamente como morph targets válidos en el GLB de salida
  (`pytest backend/tests/test_expressions.py`, valida estructura del glTF).

### Módulo 6 — Pulido (post-aprobación del usuario)
- Libre, sin gate de verificación fijo predefinido.

## Convenciones de código

- Python: type hints obligatorios en funciones públicas, `ruff` para lint.
- Un test por módulo como mínimo, en `backend/tests/`, antes de marcar el
  módulo como completo.
- Commits atómicos, un commit por sub-tarea, mensaje descriptivo.

## Historial de checkpoints

(Se añade una entrada aquí cada vez que un módulo se completa y verifica.
Formato: `[Módulo N] fecha — resumen de qué se hizo y qué decisiones se tomaron.`)

- **[Módulo 0] 2026-08-18** — Estructura de repo creada: `backend/app/main.py`
  (FastAPI con `GET /health`), `backend/scripts/inspect_glb.py` (carga un GLB
  vía `bpy` en modo `--background`, imprime vértices, huesos, bounding box y
  nº de materiales; funciona tanto invocado directamente dentro de Blender
  como vía wrapper `python inspect_glb.py <glb>` que reinvoca Blender como
  subproceso), `frontend/` (Vite + Three.js mínimo: input de archivo GLB,
  `OrbitControls`, sin lógica adicional), `samples/README.md`,
  `requirements.txt`, `backend/tests/test_setup.py`.
  Decisión: Blender no estaba instalado en el sistema; se instaló Blender
  4.5 LTS vía `winget` (`BlenderFoundation.Blender.LTS.4.5`) y se añadió su
  directorio al `PATH` de usuario, ya que la arquitectura del proyecto
  depende de invocar `blender --background` como subproceso (no se usó el
  paquete `bpy` de PyPI para mantener la versión de Blender bajo control
  explícito vía winget). Se generó `samples/test_cube.glb` (cubo + armature
  de 1 hueso, creado con Blender, sin dependencias de licencia externa) para
  validar `inspect_glb.py` end-to-end.
  Verificación: `pytest backend/tests/test_setup.py` → 2 passed (health
  endpoint + Blender headless responde). `python backend/scripts/inspect_glb.py
  samples/test_cube.glb` → ejecuta sin errores, imprime 24 vértices, 1 hueso
  ("Bone"), bounding box y 1 material.
  Corrección post-verificación: el conteo inicial daba 66 vértices en lugar
  de 24. Causa raíz: el importador glTF de Blender crea, por cada hueso, un
  objeto MESH auxiliar (p.ej. "Icosphere", 42 vértices) usado solo como
  widget visual de pose (`pose_bone.custom_shape`); no es geometría del
  modelo. `inspect_glb.py` ahora excluye explícitamente los objetos
  referenciados como `custom_shape` de huesos antes de contar vértices y
  calcular el bounding box. Relevante para el Módulo 1: cualquier código que
  itere `bpy.data.objects` tras un `import_scene.gltf` con armature debe
  aplicar el mismo filtro.
