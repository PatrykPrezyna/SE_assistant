package RoboticArmUseCases {

    private import RoboticArmRequirements::*;

    // ------------------------------------------------------------------
    // Actors
    // ------------------------------------------------------------------

    actor def Operator {
        doc /*
        The human operator who controls and monitors the robotic arm system.
        */
    }

    actor def ControlSystem {
        doc /*
        The external computer or automation system that commands the robotic arm.
        */
    }

    actor def Technician {
        doc /*
        The technician responsible for teaching new positions and maintenance.
        */
    }

    actor def Environment {
        doc /*
        The physical environment and objects being manipulated by the arm.
        */
    }

    // ------------------------------------------------------------------
    // Use Cases
    // ------------------------------------------------------------------

    use case def InitializeSystem {
        doc /*
        The robotic arm system powers up, performs self-diagnostics,
        and reaches a safe home position.
        */
        subject : RobotArmSystem;
        actor operator : Operator;
    }

    use case def PickAndPlace {
        doc /*
        The robotic arm identifies, grasps, and relocates an object from
        a source location to a target location. This is the primary use case.
        The detailed steps are shown in the activity diagram.
        */
        subject : RobotArmSystem;
        actor operator : Operator;
        actor control : ControlSystem;
        
        satisfy REQ-200;  // Object weight (10-500g)
        satisfy REQ-204;  // Reach radius
        satisfy REQ-302;  // X-axis travel
        satisfy REQ-203;  // Speed (10-30s cycle)
    }

    use case def MonitorStatus {
        doc /*
        The operator or control system monitors the arm's position, status,
        and any error conditions via the display and feedback interface.
        */
        subject : RobotArmSystem;
        actor operator : Operator;
        actor control : ControlSystem;
    }

    use case def TeachNewPosition {
        doc /*
        A technician or advanced operator manually teaches the arm a new
        target position or sequence using direct control or a teach pendant,
        storing the configuration for later use.
        */
        subject : RobotArmSystem;
        actor technician : Technician;
        actor operator : Operator;
        
        satisfy REQ-272;  // Modular architecture supports flexible positioning
    }

    use case def PerformMaintenance {
        doc /*
        A technician performs routine maintenance, diagnostics, calibration,
        or replacement of worn components (servos, links, bearings).
        */
        subject : RobotArmSystem;
        actor technician : Technician;
    }

    use case def PowerManagement {
        doc /*
        The system manages power distribution to all joints and the controller,
        with support for USB or external power sources.
        */
        subject : RobotArmSystem;
        satisfy REQ-260;  // Power interface
    }

    use case def ExpandModularArm {
        doc /*
        The system architecture allows for expanding the arm with additional
        joints (up to 6 DOF) without redesigning core components.
        */
        subject : RobotArmSystem;
        satisfy REQ-272;  // Modular architecture
    }

    // ------------------------------------------------------------------
    // Use Case Diagram Instance
    // ------------------------------------------------------------------

    use case useDiagram RobotArmUseCaseDiagram for RobotArmSystem {
        actor operator : Operator;
        actor control : ControlSystem;
        actor tech : Technician;
        actor env : Environment;

        use case pickPlace : PickAndPlace;
        use case initialize : InitializeSystem;
        use case monitor : MonitorStatus;
        use case teach : TeachNewPosition;
        use case maint : PerformMaintenance;
        use case power : PowerManagement;
        use case expand : ExpandModularArm;

        // Operator interactions
        connection opInitialize from operator to initialize;
        connection opPickPlace from operator to pickPlace;
        connection opMonitor from operator to monitor;
        connection opTeach from operator to teach;

        // Control system interactions
        connection ctrlPickPlace from control to pickPlace;
        connection ctrlMonitor from control to monitor;

        // Technician interactions
        connection techTeach from tech to teach;
        connection techMaint from tech to maint;

        // Environment interactions (object manipulation)
        connection envPickPlace from env to pickPlace;

        // System-level interactions
        connection sysInitialize to power;
        connection sysExpand to pickPlace;
    }

    // ------------------------------------------------------------------
    // Activity Diagram - Pick and Place Sequence
    // ------------------------------------------------------------------

    activity def PickAndPlaceActivity {
        doc /*
        Detailed activity flow for the PickAndPlace use case showing:
        1. Move to source position
        2. Grip the object
        3. Move to target position
        4. Release the object
        */

        in start;
        out success;
        out failure;

        // Activities in the flow
        activity moveToSource {
            doc /* Move arm end effector to source location */
        }

        activity gripObject {
            doc /* Close gripper to securely grasp object */
        }

        activity moveToTarget {
            doc /* Move arm with grasped object to target location */
        }

        activity releaseObject {
            doc /* Open gripper to release object at target */
        }

        activity verifyPlacement {
            doc /* Verify object is correctly placed */
        }

        // Decision points
        decision pickDecision;
        decision placeDecision;

        // Control flow
        start --[transition]--> moveToSource;
        moveToSource --[transition]--> pickDecision;
        pickDecision --[gripped]--> moveToTarget;
        pickDecision --[not gripped]--> failure;
        moveToTarget --[transition]--> releaseObject;
        releaseObject --[transition]--> verifyPlacement;
        verifyPlacement --[placed]--> success;
        verifyPlacement --[not placed]--> placeDecision;
        placeDecision --[retry]--> moveToTarget;
        placeDecision --[abort]--> failure;
    }
}
