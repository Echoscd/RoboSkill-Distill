# Toolbox scoring rubric

Scores are engineering metadata. They should change when implementation or
evidence changes, and every score change should explain why.

## Generality (1-10)

| Score | Meaning |
| --- | --- |
| 1 | One scene, seed, object instance, and embodiment. |
| 2 | Same task and object class with small pose variation. |
| 3 | Same task across several instances or seeds. |
| 4 | Closely related tasks with the same object and embodiment. |
| 5 | Several objects sharing strong assumptions, such as color and rigid shape. |
| 6 | Cross-task use within one manipulation family. |
| 7 | Cross-object and cross-task use with configurable perception or geometry. |
| 8 | Broad manipulation primitive with limited embodiment assumptions. |
| 9 | Embodiment-agnostic capability with typed adapters. |
| 10 | Domain-independent utility with no task- or robot-specific semantics. |

The score is capped by the narrowest hard-coded assumption. A function named
`locate_object` that only supports HSV color masks is not a 9 or 10.

## Level (1-10)

| Score | Meaning |
| --- | --- |
| 1 | Device read/write or pure scalar/array operation. |
| 2 | Single transform, filter, segmentation, or state read. |
| 3 | One geometric estimate or physical measurement. |
| 4 | Multi-step perception or one physical predicate. |
| 5 | Candidate generation, ranking, or multi-signal state estimate. |
| 6 | Closed-loop verifier or short reusable manipulation procedure. |
| 7 | Motion/grasp plan assembled from perception, geometry, and IK. |
| 8 | Complete reusable skill with recovery branches. |
| 9 | Multi-skill task policy. |
| 10 | Episode-level autonomous workflow or teacher/learner loop. |

Level measures composition complexity, not code length. A long calibration
formula can remain level 2; a short declaration that orchestrates perception,
planning, execution, and recovery can be level 8.

## Dependency rule

For every dependency edge `A -> B`, where A calls B:

```text
level(A) > level(B)
```

Equal-level and upward dependencies are rejected. This keeps the toolbox a
directed acyclic hierarchy and prevents two high-level skills from becoming
implicitly coupled.

