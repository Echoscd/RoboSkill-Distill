"""Conservative arm-link OBB checks along declared joint-linear segments.

No scene discovery, simulator privileged state, execution, or success policy.
STL collision meshes are enclosed by local boxes. Overlap is a conservative
rejection, not proof that the underlying triangle surfaces touch.
"""

from __future__ import annotations

import hashlib
import json
import itertools
import math
from pathlib import Path
import struct
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


def vector(value: Any, size: int, label: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (size,) or not np.isfinite(result).all():
        raise ValueError(f"{label} must contain {size} finite numbers")
    return result


def pose_matrix(value: Any) -> np.ndarray:
    p = vector(value, 7, "pose")
    norm = np.linalg.norm(p[3:])
    if norm < 1e-8:
        raise ValueError("pose quaternion must be nonzero")
    x, y, z, w = p[3:] / norm
    result = np.eye(4)
    result[:3, :3] = [
        [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
        [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)],
    ]
    result[:3, 3] = p[:3]
    return result


def _rotation(axis: Any, angle: float) -> np.ndarray:
    unit = vector(axis, 3, "axis")
    if np.linalg.norm(unit) < 1e-8:
        raise ValueError("joint axis must be nonzero")
    unit /= np.linalg.norm(unit)
    x, y, z = unit
    skew = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + math.sin(angle)*skew + (1-math.cos(angle))*(skew @ skew)


def _origin(element: Any) -> np.ndarray:
    result = np.eye(4)
    if element is None:
        return result
    result[:3, 3] = vector(element.get("xyz", "0 0 0").split(), 3, "origin.xyz")
    roll, pitch, yaw = vector(element.get("rpy", "0 0 0").split(), 3, "origin.rpy")
    result[:3, :3] = _rotation([0, 0, 1], yaw) @ _rotation([0, 1, 0], pitch) @ _rotation([1, 0, 0], roll)
    return result


def stl_vertices(path: Path) -> np.ndarray:
    data = path.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else 0
    if count and len(data) == 84 + 50*count:
        triangles = np.frombuffer(data, dtype=np.dtype([
            ("normal", "<f4", 3), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")
        ]), offset=84, count=count)
        vertices = triangles["vertices"].reshape(-1, 3).astype(float)
    else:
        vertices = np.asarray([
            line.split()[1:] for line in data.decode("ascii").splitlines()
            if line.strip().startswith("vertex ")
        ], dtype=float)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not vertices.size or not np.isfinite(vertices).all():
        raise ValueError(f"invalid or empty STL: {path}")
    return np.unique(vertices, axis=0)


def stl_bounds(path: Path) -> tuple[np.ndarray, np.ndarray]:
    vertices = stl_vertices(path)
    return vertices.min(axis=0), vertices.max(axis=0)


def _closest_simplex(simplex):
    """Closest convex combination to origin, preserving a simplex of <=4 points."""
    best = None
    for size in range(1, min(4, len(simplex))+1):
        for indices in itertools.combinations(range(len(simplex)), size):
            points = np.asarray([simplex[i] for i in indices])
            gram = points @ points.T
            system = np.block([[gram, np.ones((size, 1))], [np.ones((1, size)), np.zeros((1, 1))]])
            weights = np.linalg.lstsq(system, np.r_[np.zeros(size), 1], rcond=None)[0][:size]
            if np.min(weights) < -1e-10:
                continue
            weights = np.maximum(weights, 0)
            weights /= weights.sum()
            closest = weights @ points
            distance = float(closest @ closest)
            if best is None or distance < best[0]:
                best = (distance, closest, [point for point, weight in zip(points, weights) if weight > 1e-10])
    return best[1], best[2]


def convex_overlap(vertices_a, vertices_b, padding_a, padding_b, rotation_a=None, rotation_b=None) -> bool:
    """Conservative GJK rejection on convex mesh hulls, with local-box padding.

    False only with a separating support plane; degeneracy/iteration limit is
    treated as overlap. Convex hulls still enclose concave meshes conservatively.
    """
    direction = np.mean(vertices_b, axis=0)-np.mean(vertices_a, axis=0)
    if np.linalg.norm(direction) < 1e-10:
        direction = np.array([1., 0, 0])
    rotation_a = np.eye(3) if rotation_a is None else rotation_a
    rotation_b = np.eye(3) if rotation_b is None else rotation_b

    def support(axis):
        a = vertices_a[np.argmax(vertices_a @ axis)]
        b = vertices_b[np.argmin(vertices_b @ axis)]
        return (a-b + padding_a*(rotation_a @ np.sign(axis @ rotation_a))
            + padding_b*(rotation_b @ np.sign(axis @ rotation_b)))

    simplex = [support(direction)]
    closest = simplex[0]
    for _ in range(48):
        if float(closest @ closest) < 1e-18:
            return True
        direction = -closest
        point = support(direction)
        if float(point @ direction) < -1e-10:
            return False
        if any(np.linalg.norm(point-old) < 1e-12 for old in simplex):
            return True
        closest, simplex = _closest_simplex([*simplex, point])
    return True


def boxes_overlap(a: tuple, b: tuple) -> bool:
    """15-axis separating-axis test; touching counts as overlap."""
    ac, ar, ah = a
    bc, br, bh = b
    delta = bc - ac
    axes = [*ar.T, *br.T, *(np.cross(x, y) for x in ar.T for y in br.T)]
    for axis in axes:
        if np.linalg.norm(axis) < 1e-10:
            continue
        axis = axis / np.linalg.norm(axis)
        radius = float(np.abs(axis @ ar) @ ah + np.abs(axis @ br) @ bh)
        if abs(float(delta @ axis)) > radius + 1e-10:
            return False
    return True


def load_context(path: str) -> dict:
    source = Path(path).expanduser().resolve()
    context = json.loads(source.read_text(encoding="utf-8"))
    if context.get("frame") != "world" or not context.get("provenance"):
        raise ValueError("collision context requires frame=world and measured/calibrated provenance")
    observations = context.get("based_on")
    if not isinstance(observations, list) or not observations or any(not isinstance(x, str) or not x for x in observations):
        raise ValueError("collision context based_on must contain observation IDs")
    times = vector([context.get("observed_at_s"), context.get("expires_at_s")], 2, "context times")
    if not 0 <= times[0] < times[1]:
        raise ValueError("collision context expiry must exceed acquisition time")
    if not isinstance(context.get("arms"), dict) or not context["arms"]:
        raise ValueError("collision context requires per-arm public URDF paths")
    if not isinstance(context.get("obstacles"), list) or not context["obstacles"]:
        raise ValueError("empty obstacle lists cannot establish scene clearance")
    identifiers = set()
    for obstacle in context["obstacles"]:
        if not isinstance(obstacle.get("id"), str) or not obstacle["id"] or obstacle["id"] in identifiers:
            raise ValueError("obstacle IDs must be unique non-empty strings")
        identifiers.add(obstacle["id"])
        pose_matrix(obstacle["pose_world"])
        if np.any(vector(obstacle["size_m"], 3, "obstacle size_m") <= 0):
            raise ValueError("obstacle dimensions must be positive")
    context["_directory"] = str(source.parent)
    context["_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    return context


class ArmCollisionChecker:
    """One public arm model against explicitly declared static obstacle boxes."""

    def __init__(self, arm: str, profile: dict, context: dict, *, margin_m: float = 0.005,
                 max_joint_step_rad: float = 0.025, check_self_collision: bool = True,
                 other_arm_profiles: dict | None = None, other_arm_states: dict | None = None,
                 robot_pair_margin_m: float = 0.0):
        if not math.isfinite(margin_m) or not 0 <= margin_m <= 0.1:
            raise ValueError("margin_m must be in [0,0.1]")
        if not math.isfinite(max_joint_step_rad) or not 0 < max_joint_step_rad <= 0.1:
            raise ValueError("max_joint_step_rad must be in (0,0.1]")
        self.margin = margin_m
        if not math.isfinite(robot_pair_margin_m) or not 0 <= robot_pair_margin_m <= .1:
            raise ValueError("robot_pair_margin_m must be in [0,0.1]")
        self.robot_margin = robot_pair_margin_m
        self.step = max_joint_step_rad
        self.context = context
        self.arm = arm
        self.check_self = check_self_collision
        self.other_bodies = []
        self.other_states = other_arm_states or {}
        model = profile["intrinsics"]["model"]
        self.joints = model["joints"]
        self.chain = model["chain"]
        if model.get("format") != "serial_chain" or [x.get("joint") for x in self.chain] != list(range(len(self.joints))):
            raise ValueError("checker supports serial_chain with one revolute joint per link only")
        if any(x.get("type") != "revolute" for x in self.joints):
            raise ValueError("checker currently requires revolute joints")
        mount = profile["extrinsics"]["mount"]
        if mount.get("parent") != "world":
            raise ValueError("checker requires a world-mounted arm profile")
        self.mount = pose_matrix([*mount["translation_m"], *mount["rotation_xyzw"]])
        urdf = Path(context["arms"][arm]["urdf_path"]).expanduser()
        if not urdf.is_absolute():
            urdf = Path(context["_directory"]) / urdf
        self.urdf = urdf.resolve()
        root = ET.parse(self.urdf).getroot()
        self.bodies = []
        self.vertices = []
        self.model_hashes = {str(self.urdf): hashlib.sha256(self.urdf.read_bytes()).hexdigest()}
        previous_child = None
        for index, joint in enumerate(self.joints):
            xml_joint = root.find(f"joint[@name='{joint['name']}']")
            if xml_joint is None or xml_joint.get("type") not in ("revolute", "continuous"):
                raise ValueError(f"URDF missing revolute joint {joint['name']}")
            if previous_child is not None and xml_joint.find("parent").get("link") != previous_child:
                raise ValueError("URDF active joints must form the same uninterrupted serial chain")
            # Ensure meshes and profile FK describe the same link frames.
            chain_link = self.chain[index]
            reference = float(chain_link.get("reference", 0))
            origin = pose_matrix(chain_link["origin"])
            anchor = vector(chain_link["anchor"], 3, "joint anchor")
            if np.linalg.norm(anchor) > 1e-8 or reference != 0:
                raise ValueError("URDF alignment requires zero anchor and reference")
            axis = vector(xml_joint.find("axis").get("xyz").split(), 3, "URDF axis")
            if not np.allclose(origin, _origin(xml_joint.find("origin")), atol=1e-5) or not np.allclose(axis, chain_link["axis"], atol=1e-5):
                raise ValueError(f"URDF/profile frame mismatch at {joint['name']}")
            name = xml_joint.find("child").get("link")
            previous_child = name
            link = root.find(f"link[@name='{name}']")
            collisions = [] if link is None else link.findall("collision")
            if not collisions:
                raise ValueError(f"missing collision geometry for active link {name}")
            for collision in collisions:
                geometry = collision.find("geometry")
                box, mesh = geometry.find("box"), geometry.find("mesh")
                if box is not None:
                    size = vector(box.get("size").split(), 3, "URDF box")
                    if np.any(size <= 0):
                        raise ValueError("URDF box size must be positive")
                    low, high = -size/2, size/2
                    vertices = np.asarray(list(itertools.product(*zip(low, high))))
                elif mesh is not None:
                    filename = mesh.get("filename", "")
                    if "://" in filename or not filename.lower().endswith(".stl"):
                        raise ValueError("only local relative/absolute STL collision meshes are supported")
                    mesh_path = (self.urdf.parent / filename).resolve()
                    vertices = stl_vertices(mesh_path)
                    scale = vector(mesh.get("scale", "1 1 1").split(), 3, "mesh scale")
                    if np.any(scale <= 0):
                        raise ValueError("mesh scales must be positive")
                    vertices = vertices*scale
                    low, high = vertices.min(axis=0), vertices.max(axis=0)
                    self.model_hashes[str(mesh_path)] = hashlib.sha256(mesh_path.read_bytes()).hexdigest()
                else:
                    raise ValueError("unsupported collision geometry; use box or STL")
                self.bodies.append((index, name, _origin(collision.find("origin")), (low+high)/2, (high-low)/2))
                self.vertices.append(vertices)
        self.obstacles = []
        for obstacle in context["obstacles"]:
            transform = pose_matrix(obstacle["pose_world"])
            self.obstacles.append((obstacle["id"], (transform[:3, 3], transform[:3, :3], vector(obstacle["size_m"], 3, "obstacle size")/2)))
        self.obstacle_lows, self.obstacle_highs = self._bounds([item[1] for item in self.obstacles])
        for other, other_profile in (other_arm_profiles or {}).items():
            if other == arm:
                raise ValueError("other_arm_profiles must exclude the selected arm")
            state = self.other_states[other]
            if not math.isfinite(state["timestamp"]):
                raise ValueError("other arm snapshot requires a finite session timestamp")
            model = ArmCollisionChecker(other, other_profile, context, margin_m=margin_m,
                max_joint_step_rad=max_joint_step_rad, check_self_collision=False,
                robot_pair_margin_m=robot_pair_margin_m)
            for body_index, (_, link, box) in enumerate(model.body_boxes(state["positions"], padding_m=self.robot_margin)):
                self.other_bodies.append((other, link, box, model.world_vertices(state["positions"], body_index)))
            self.model_hashes.update(model.model_hashes)

    @staticmethod
    def _bounds(boxes):
        if not boxes:
            return np.empty((0, 3)), np.empty((0, 3))
        centers = np.asarray([b[0] for b in boxes])
        extents = np.asarray([np.abs(b[1]) @ b[2] for b in boxes])
        return centers-extents, centers+extents

    def body_boxes(self, q, *, padding_m=None):
        transforms = self.link_transforms(q)
        result = []
        for index, name, origin, center, half in self.bodies:
            transform = transforms[index] @ origin
            padding = self.margin if padding_m is None else padding_m
            box = (transform[:3, :3] @ center + transform[:3, 3], transform[:3, :3], half+padding)
            result.append((index, name, box))
        return result

    def world_vertices(self, q, body_index):
        index, _, origin, _, _ = self.bodies[body_index]
        transform = self.link_transforms(q)[index] @ origin
        return self.vertices[body_index] @ transform[:3, :3].T + transform[:3, 3]

    def link_transforms(self, q: Any) -> list[np.ndarray]:
        q = vector(q, len(self.joints), "joint positions")
        current = self.mount.copy()
        result = []
        for index, link in enumerate(self.chain):
            limits = self.joints[index]["limits"]
            if not float(limits["min"]) <= q[index] <= float(limits["max"]):
                raise ValueError(f"joint {index} outside declared limits")
            current = current @ pose_matrix(link["origin"])
            rotation = np.eye(4)
            rotation[:3, :3] = _rotation(link["axis"], float(q[index]))
            current = current @ rotation
            result.append(current.copy())
        return result

    def check(self, start_joints: list, joint_stages: list[dict]) -> dict:
        previous = vector(start_joints, len(self.joints), "start_joints")
        if not joint_stages or len(joint_stages) > 16:
            raise ValueError("joint_stages must contain 1-16 stages")
        tested = 0
        for stage in [{"stage": "start", "joints": previous.tolist()}, *joint_stages]:
            target = vector(stage["joints"], len(self.joints), "stage joints")
            if not isinstance(stage["stage"], str) or not stage["stage"]:
                raise ValueError("stage names must be non-empty strings")
            steps = max(1, math.ceil(float(np.max(np.abs(target-previous)))/self.step))
            if tested + steps + 1 > 20000:
                raise ValueError("path exceeds 20000 samples; reduce path length")
            for sample in range(steps+1):
                fraction = sample/steps
                q = previous + fraction*(target-previous)
                tested += 1
                bodies = self.body_boxes(q)
                pair_bodies = self.body_boxes(q, padding_m=self.robot_margin)
                for body_index, (index, name, body) in enumerate(bodies):
                    extent = np.abs(body[1]) @ body[2]
                    possible = np.flatnonzero(np.all(self.obstacle_highs >= body[0]-extent, axis=1)
                        & np.all(self.obstacle_lows <= body[0]+extent, axis=1))
                    for obstacle_index in possible:
                        obstacle_id, obstacle = self.obstacles[obstacle_index]
                        if boxes_overlap(body, obstacle):
                            return self._report(False, tested, {"stage": stage["stage"], "segment_fraction": fraction,
                                "joints": q.tolist(), "collision_type": "environment", "link": name, "obstacle_id": obstacle_id})
                    if self.check_self:
                        pair_body = pair_bodies[body_index][2]
                        for other_body_index in range(body_index+1, len(bodies)):
                            other_index, other_name, other_box = pair_bodies[other_body_index]
                            if (abs(index-other_index) > 1 and boxes_overlap(pair_body, other_box)
                                    and convex_overlap(self.world_vertices(q, body_index), self.world_vertices(q, other_body_index), self.robot_margin, self.robot_margin, pair_body[1], other_box[1])):
                                return self._report(False, tested, {"stage": stage["stage"], "segment_fraction": fraction,
                                    "joints": q.tolist(), "collision_type": "self", "link": name, "other_link": other_name})
                    for other_arm, other_link, other_box, other_vertices in self.other_bodies:
                        pair_body = pair_bodies[body_index][2]
                        if (boxes_overlap(pair_body, other_box)
                                and convex_overlap(self.world_vertices(q, body_index), other_vertices, self.robot_margin, self.robot_margin, pair_body[1], other_box[1])):
                            return self._report(False, tested, {"stage": stage["stage"], "segment_fraction": fraction,
                                "joints": q.tolist(), "collision_type": "inter_arm", "link": name,
                                "other_arm": other_arm, "other_link": other_link})
            previous = target
        return self._report(True, tested, None)

    def _report(self, clear: bool, samples: int, overlap: Any) -> dict:
        return {
            "status": "clear_at_samples" if clear else "overlap",
            "collision_free_at_samples": clear, "samples_tested": samples,
            "first_overlap": overlap, "arm": self.arm,
            "checked_links": sorted({body[1] for body in self.bodies}),
            "obstacle_ids": [item[0] for item in self.obstacles],
            "margin_m": self.margin, "max_joint_step_rad": self.step,
            "robot_pair_margin_m": self.robot_margin,
            "robot_pair_margin_scope": "Separate nominal robot geometry budget; perception target uncertainty is not added. Zero padding does not certify calibration accuracy.",
            "context_sha256": self.context["_sha256"], "model_sha256": self.model_hashes,
            "based_on": self.context["based_on"],
            "observed_at_s": self.context["observed_at_s"], "expires_at_s": self.context["expires_at_s"],
            "scope": "active arm links vs declared environment, non-adjacent active links and supplied stationary other-arm snapshots; joint-linear samples; conservative OBBs",
            "scene_coverage": self.context.get("coverage", {"kind": "declared_boxes", "unobserved_space": "unknown"}),
            "self_collision_checked": self.check_self,
            "self_collision_exclusions": "same and directly adjacent active links only",
            "robot_pair_narrow_phase": "convex mesh hull support-plane separation; degenerate or unresolved pairs conservatively overlap",
            "inter_arm_collision_checked": bool(self.other_bodies),
            "other_arm_snapshots": self.other_states,
            "unmodeled_arms": sorted(set(self.context["arms"]) - {self.arm} - set(self.other_states)),
            "other_arm_motion_assumption": "Stationary throughout selected-arm motion; synchronized dual-arm motion is not checked.",
            "gripper_collision_checked": False,
            "continuous_collision_certified": False, "execution_validated": None,
        }
