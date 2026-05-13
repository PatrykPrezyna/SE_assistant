package RoboticArmRequirements {

    requirement def RobotArmRequirement;

    requirement <'SYS-001'> RoboticArmSystemRequirements : RobotArmRequirement {
        doc /*
        The robotic arm system shall satisfy the defined architecture,
        performance, and interface requirements.
        */
    }

    package ArchitectureRequirements {
        requirement <'REQ-272'> ModularArchitecture : RobotArmRequirement {
            doc /*
            The robotic arm shall allow expansion with additional axes up to 6 DOF.
            */
        }
    }

    package PerformanceRequirements {
        requirement <'REQ-200'> ObjectWeight : RobotArmRequirement {
            doc /*
            The robotic arm shall grip and lift objects weighing 10 g to 500 g
            without dropping them.
            */
        }

        requirement <'REQ-302'> XAxisTravel : RobotArmRequirement {
            doc /*
            The robotic arm shall provide 1000 mm of travel along the X axis
            to access an item on a shelf.
            */
        }

        requirement <'REQ-203'> Speed : RobotArmRequirement {
            doc /*
            The robotic arm shall perform a pick-and-place cycle in 10 s to 30 s.
            */
        }

        requirement <'REQ-201'> Accuracy : RobotArmRequirement {
            doc /*
            The robotic arm shall place objects with a positional accuracy of ±3 mm.
            */
        }

        requirement <'REQ-204'> ReachRadius : RobotArmRequirement {
            doc /*
            The robotic arm shall provide a reach radius of 180 mm.
            */
        }
    }

    package InterfaceRequirements {
        requirement <'REQ-260'> PowerInterface : RobotArmRequirement {
            doc /*
            The robotic arm shall accept power through a USB power interface
            and shall be connectable to a grid power source using a compatible
            USB power adapter, such as a laptop or phone charger.
            */
        }
    }
}