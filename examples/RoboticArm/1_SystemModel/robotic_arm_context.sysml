package RoboticArmContext {

    // Load alongside robotic_arm_bdd.sysml (and robotic_arm_req.sysml) so the
    // RobotArmSystem typing and REQ-* satisfy edges below resolve.
    private import RobotArmLogicalArchitecture::RobotArmSystem;
    private import RoboticArmRequirements::*;

    // ------------------------------------------------------------------
    // Context elements — current, single-printer cell (Project Charter
    // status quo, section 2). The dual-printer expansion (section 4) is
    // out of scope for this diagram.
    // ------------------------------------------------------------------

    part def BuildPlatform {
        doc /*
        The build plate area of the 3D printer that holds the completed
        part until the robotic arm removes it.
        */
    }

    part def Printer {
        doc /*
        The desktop 3D printer serviced by the robotic arm. Sits at the
        edge of the arm's 180 mm reach radius.
        */
        part buildPlatform : BuildPlatform;

        satisfy REQ-204;  // reach radius (180 mm) sizes the printer's placement
    }

    part def StorageShelf {
        doc /*
        Central storage shelf where the robotic arm places parts removed
        from the printer's build platform.
        */
        satisfy REQ-302;  // X-axis travel needed to reach the shelf
    }

    // ------------------------------------------------------------------
    // Context block: the robotic arm and the external elements it
    // interacts with
    // ------------------------------------------------------------------

    part def RoboticArmOperationalContext {
        doc /*
        Operating context of the robotic arm in the current, single-printer
        manufacturing cell: the arm removes a completed part from the
        printer's build platform and transfers it to the storage shelf.
        */
        part printer : Printer;
        part robot : RobotArmSystem;
        part shelf : StorageShelf;
    }

    // Usage-level instance
    part armContext : RoboticArmOperationalContext;

    // ------------------------------------------------------------------
    // Internal Block Diagram — context interactions
    // ------------------------------------------------------------------

    ibd def RoboticArmContextIBD of RoboticArmOperationalContext {
        ref printer : Printer;
        ref robot : RobotArmSystem;
        ref shelf : StorageShelf;

        connection pickFromPrinter : printer to robot {
            // robot removes the completed part from the printer's build platform
        }

        connection placeOnShelf : robot to shelf {
            // robot transfers the removed part to the storage shelf
        }
    }
}
