"""Read a device-selected URDF chain; no SDK, simulator or numerical dependencies."""

import math
from pathlib import Path
from xml.etree import ElementTree

from kinex.motion import vector


def rpy_quaternion(roll, pitch, yaw):
    cr, sr = math.cos(roll/2), math.sin(roll/2)
    cp, sp = math.cos(pitch/2), math.sin(pitch/2)
    cy, sy = math.cos(yaw/2), math.sin(yaw/2)
    return [sr*cp*cy-cr*sp*sy, cr*sp*cy+sr*cp*sy, cr*cp*sy-sr*sp*cy, cr*cp*cy+sr*sp*sy]


def numbers(element, attribute, default):
    return vector([float(v) for v in (element.get(attribute, default) if element is not None else default).split()], 3, attribute)


def read_chain(path, base_link, tip_link, xml=None):
    root = ElementTree.fromstring(xml) if xml is not None else ElementTree.parse(Path(path)).getroot()
    if root.tag != "robot":
        raise ValueError("Expected a URDF robot")
    links = [link.attrib["name"] for link in root.findall("link")]
    if len(links) != len(set(links)) or base_link not in links or tip_link not in links or base_link == tip_link:
        raise ValueError("URDF requires unique links and distinct existing base_link/tip_link")
    parents, names = {}, set()
    for joint in root.findall("joint"):
        name = joint.attrib["name"]
        parent, child = joint.find("parent"), joint.find("child")
        if parent is None or child is None or parent.attrib["link"] not in links or child.attrib["link"] not in links:
            raise ValueError(f"Invalid parent/child for URDF joint {name}")
        if name in names or child.attrib["link"] in parents:
            raise ValueError("URDF joint names and child links must be unique")
        names.add(name)
        parents[child.attrib["link"]] = joint
    selected, visited = [], set()
    current = tip_link
    while current != base_link:
        if current in visited or current not in parents:
            raise ValueError("tip_link is not a descendant of base_link in an acyclic chain")
        visited.add(current)
        joint = parents[current]
        selected.append(joint)
        current = joint.find("parent").attrib["link"]
    joints, chain = [], []
    for joint in reversed(selected):
        origin = joint.find("origin")
        link = {"origin": numbers(origin, "xyz", "0 0 0") + rpy_quaternion(*numbers(origin, "rpy", "0 0 0"))}
        kind = joint.attrib["type"]
        if kind == "fixed":
            chain.append(link)
            continue
        if kind not in {"revolute", "continuous", "prismatic"} or joint.find("mimic") is not None:
            raise ValueError("Selected chain must contain independent scalar joints; mimic/planar/floating joints are unsupported")
        limit = joint.find("limit")
        bounds = None
        if kind != "continuous":
            if limit is None or "lower" not in limit.attrib or "upper" not in limit.attrib:
                raise ValueError(f"Missing position limits for {joint.attrib['name']}")
            bounds = {"min": float(limit.attrib["lower"]), "max": float(limit.attrib["upper"])}
            if not math.isfinite(bounds["min"]) or not math.isfinite(bounds["max"]) or bounds["min"] >= bounds["max"]:
                raise ValueError("Invalid URDF position limits")
        rates = {key: float(limit.attrib[attr]) if limit is not None and attr in limit.attrib else None
                 for key, attr in (("max_velocity", "velocity"), ("max_effort", "effort"))}
        if any(v is not None and (not math.isfinite(v) or v <= 0) for v in rates.values()):
            raise ValueError("URDF velocity/effort limits must be positive")
        axis = numbers(joint.find("axis"), "xyz", "1 0 0")
        norm = math.hypot(*axis)
        if norm == 0:
            raise ValueError("URDF joint axis must be nonzero")
        link.update(joint=len(joints), axis=[v/norm for v in axis], anchor=[0, 0, 0], reference=0)
        joints.append({"name": joint.attrib["name"], "type": kind, "limits": bounds, **rates})
        chain.append(link)
    if not joints:
        raise ValueError("Selected chain has no movable joints")
    return {"joints": joints, "chain": chain}
