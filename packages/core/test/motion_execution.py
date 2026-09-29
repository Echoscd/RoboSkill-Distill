"""Exercise trajectory duration and planning limits."""

import copy
import math
import unittest

from kinex.trajectory import trajectory, planning_limits


PROFILE = {
    "name": "arm", "type": "joint", "intrinsics": {
        "model": {"format": "joints", "joints": [{"name": "j", "type": "revolute",
            "limits": {"min": -2, "max": 2}, "max_velocity": 0.5, "max_acceleration": 1.0}]},
        "home": None, "frames": {}, "control": {"mode": "position"},
        "feedback": {"velocities": True, "efforts": False},
    },
}


class MotionTests(unittest.TestCase):
    def test_native_commands_pass_raw_targets_and_still_validate_structure(self):
        from kinex.joint_control import command
        from kinex.scalar_control import command as scalar
        from kinex.velocity import command as velocity

        profile = copy.deepcopy(PROFILE)
        args = {"actions": [[100]], "duration_s": .1}
        with self.assertRaises(ValueError):
            command(profile, args)
        profile["intrinsics"]["control"]["limit_handling"] = "native"
        self.assertEqual(command(profile, args), args)
        for target in ([True], [math.nan], [math.inf], [], [1, 2]):
            with self.assertRaises(ValueError):
                command(profile, {**args, "actions": [[0], target]})
        joints = profile["intrinsics"]["model"]["joints"]
        self.assertTrue(trajectory(joints, [2.001], [100], .01, check_limits=False).actions)
        tool = {"intrinsics": {"control": {"mode": "position", "bounds": {"min": 0, "max": 1},
            "resolution": None, "speed": None}}}
        self.assertEqual(scalar(tool, {"actions": [0, 1], "duration_s": .1})["actions"], [0, 1])
        for value in (-.001, 1.001, True, math.nan, math.inf):
            with self.assertRaises(ValueError):
                scalar(tool, {"actions": [0, value], "duration_s": .1})
        for bounds in ({"min": -1, "max": 1}, None):
            base = {"type": "velocity", "intrinsics": {"control": {"mode": "motion", "limit_handling": "native",
                "modes": {"drive": {"velocity": {"components": [
                    {"axis": "vx", "units": "m/s", "bounds": bounds}]}, "posture": None}}}}}
            args = {"mode": "drive", "velocity": {"vx": 100}, "duration_s": .1}
            self.assertEqual(velocity(base, args), args)
            for value in (True, math.nan, math.inf):
                with self.assertRaises(ValueError):
                    velocity(base, {**args, "velocity": {"vx": value}})

    def test_full_plan_duration_endpoint_and_speed_scaling(self):
        joints = [{"type": "revolute", "limits": {"min": -3, "max": 3}}] * 2
        plan = trajectory(joints, [0, 0], [2, 1], .01)
        self.assertEqual(plan.duration_s, 3.75)
        self.assertEqual(len(plan.actions), 375)
        self.assertEqual(plan.actions[-1], [2, 1])
        slow = trajectory(joints, [0, 0], [2, 1], .01, .5)
        self.assertEqual(slow.duration_s, 7.5)
        self.assertEqual(len(slow.actions), 750)
        self.assertEqual(slow.actions[-1], [2, 1])
        still = trajectory(joints, [1, 1], [1, 1], .01)
        self.assertEqual(still.duration_s, .01)
        self.assertEqual(still.actions, [[1, 1]])
        with self.assertRaises(TypeError):
            trajectory(joints, [0, 0], [2, 1], .01, duration_s=2.5)
        with self.assertRaisesRegex(ValueError, "one million"):
            trajectory(joints, [0, 0], [2, 1], .01, .0001)

    def assert_rates(self, plan, start, velocities, accelerations):
        dt = plan.duration_s / len(plan.actions)
        for i, (velocity, acceleration) in enumerate(zip(velocities, accelerations)):
            values = [start[i]] + [p[i] for p in plan.actions]
            speeds = [(b-a) / dt for a, b in zip(values, values[1:])]
            changes = [(b-a) / dt for a, b in zip([0]+speeds, speeds+[0])]
            self.assertLessEqual(max(map(abs, speeds)), velocity + 1e-8)
            self.assertLessEqual(max(map(abs, changes)), acceleration + 1e-8)

    def test_nonintegral_duration_and_mixed_joint_rate_overrides(self):
        joints = [
            {"type": "revolute", "limits": {"min": -2, "max": 2}, "max_velocity": .5},
            {"type": "prismatic", "limits": {"min": -1, "max": 1}},
        ]
        goal = [.123, .037]
        plan = trajectory(joints, [0, 0], goal, .01, .7, [.8, .2], [.8, .6])
        velocities, accelerations = planning_limits(joints, [.8, .2], [.8, .6])
        self.assertNotAlmostEqual(plan.duration_s / .01, round(plan.duration_s / .01))
        self.assertEqual(len(plan.actions), math.ceil(plan.duration_s / .01))
        self.assertEqual(plan.actions[-1], goal)
        self.assert_rates(plan, [0, 0], [v*.7 for v in velocities], [a*.7 for a in accelerations])

    def test_planner_obeys_limits_and_uses_shortest_continuous_joint_path(self):
        joints = copy.deepcopy(PROFILE["intrinsics"]["model"]["joints"])
        plan = trajectory(joints, [0], [1], .01)
        self.assert_rates(plan, [0], [.5], [1])
        self.assertEqual(plan.actions[-1], [1])
        joints[0].update(type="continuous", limits=None)
        plan = trajectory(joints, [math.pi-.1], [-math.pi+.1], .01)
        self.assertAlmostEqual(plan.actions[-1][0], math.pi+.1)
        joints[0].pop("max_acceleration")
        self.assertTrue(trajectory(joints, [0], [1], .01).actions)

    def test_planning_rates_use_available_limits_and_unit_specific_defaults(self):
        joints = [
            {"type": "revolute", "max_velocity": .2},
            {"type": "prismatic", "max_acceleration": .03},
            {"type": "continuous", "max_velocity": None, "max_acceleration": None},
        ]
        self.assertEqual(planning_limits(joints), [[.2, .1, 1], [3, .03, 3]])
        self.assertEqual(planning_limits(joints, [.1, .02, .3], [2, 2, 2]),
                         [[.1, .02, .3], [2, .03, 2]])
        self.assertEqual(planning_limits(joints, 1, 1), [[.2, 1, 1], [1, .03, 1]])
        joints[2].update(max_velocity=1000, max_acceleration=1000)
        self.assertEqual(planning_limits(joints), [[.2, .1, 1], [3, .03, 3]])
        for bad in (0, -1, True, float("nan"), [1]):
            with self.assertRaises(ValueError):
                planning_limits(joints, max_velocity=bad)

    def test_unknown_limits_still_produce_smooth_references_and_speed_scaling(self):
        for kind, velocity, acceleration, distance in (
            ("revolute", 1, 3, 1), ("prismatic", .1, .3, .1),
        ):
            joints = [{"type": kind, "limits": {"min": -2, "max": 2}}]
            plan = trajectory(joints, [0], [distance], .01)
            self.assert_rates(plan, [0], [velocity], [acceleration])
            self.assertEqual(plan.actions[-1], [distance])
            slow = trajectory(joints, [0], [distance], .01, .5)
            self.assertGreater(slow.duration_s, plan.duration_s)
            self.assert_rates(slow, [0], [velocity*.5], [acceleration*.5])


if __name__ == "__main__":
    unittest.main()
