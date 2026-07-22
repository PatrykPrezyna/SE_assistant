import re
import unittest
from pathlib import Path


class LinkLengthTraceabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.traceability_dir = Path(__file__).resolve().parent
        self.sysml_path = self.traceability_dir.parent / "1_SystemModel" / "robotic_arm_bdd.sysml"
        self.simulation_path = self.traceability_dir.parent / "Simulation" / "RoboticArm.mo"

        self.sysml_text = self.sysml_path.read_text(encoding="utf-8")
        self.simulation_text = self.simulation_path.read_text(encoding="utf-8")

    def _extract_sysml_joint_length(self, part_name: str) -> float:
        pattern = rf"part def {part_name} :> Joint\s*\{{(?P<body>.*?)\n    \}}"
        match = re.search(pattern, self.sysml_text, re.S)
        self.assertIsNotNone(match, f"Could not find SysML definition for {part_name}")

        length_match = re.search(r"attribute\s*:\>\>\s*length\s*=\s*([0-9.]+)", match.group("body"))
        self.assertIsNotNone(length_match, f"Could not find length attribute for {part_name}")

        return float(length_match.group(1)) / 1000.0

    def _extract_simulation_link_length(self, variable_name: str) -> float:
        pattern = rf"SI\.Length\s+{variable_name}\s*=\s*([0-9eE.+-]+)"
        match = re.search(pattern, self.simulation_text)
        self.assertIsNotNone(match, f"Could not find {variable_name} in the simulation model")
        return float(match.group(1))

    def test_simulation_link_lengths_match_sysml_joint_lengths(self) -> None:
        expected_pairs = {
            "L1": "ShoulderJoint",
            "L2": "ElbowJoint",
        }

        for simulation_variable, sysml_part in expected_pairs.items():
            with self.subTest(simulation_variable=simulation_variable, sysml_part=sysml_part):
                sim_length = self._extract_simulation_link_length(simulation_variable)
                sysml_length = self._extract_sysml_joint_length(sysml_part)
                self.assertAlmostEqual(
                    sim_length,
                    sysml_length,
                    places=3,
                    msg=f"{simulation_variable} should match the length attribute of {sysml_part}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
