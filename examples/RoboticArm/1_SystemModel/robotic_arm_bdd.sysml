package RobotArmLogicalArchitecture {

    private import ScalarValues::*;
    private import RoboticArmRequirements::*;

    // ------------------------------------------------------------------
    // Servo Drive hierarchy
    // ------------------------------------------------------------------

    abstract part def ServoDrive {
        attribute torque  : Real;   // stall torque [N*m]
        attribute speed   : Real;   // no-load speed [rpm]
        attribute voltage : Real;   // nominal supply voltage [V]
        attribute weight  : Real;   // mass [kg]
        attribute cost    : Real;   // unit cost [USD]
        
        satisfy REQ-203;  // Speed requirement satisfied by servo speed attribute
    }

    part def SmallServoDrive :> ServoDrive {
        attribute :>> torque  = 5.0;
        attribute :>> speed   = 90.0;
        attribute :>> voltage = 12.0;
        attribute :>> weight  = 0.25;
        attribute :>> cost    = 60.0;
    }

    part def MediumServoDrive :> ServoDrive {
        attribute :>> torque  = 25.0;
        attribute :>> speed   = 60.0;
        attribute :>> voltage = 24.0;
        attribute :>> weight  = 0.6;
        attribute :>> cost    = 180.0;
    }

    part def LargeServoDrive :> ServoDrive {
        attribute :>> torque  = 60.0;
        attribute :>> speed   = 30.0;
        attribute :>> voltage = 48.0;
        attribute :>> weight  = 1.2;
        attribute :>> cost    = 450.0;
    }

    // ------------------------------------------------------------------
    // Joint hierarchy
    // ------------------------------------------------------------------

    abstract part def Joint {
        part servo : ServoDrive;
        
        attribute length   : Real   default 100.0;      // link length [mm]
        attribute material : String default "Aluminum"; // link material
        
        satisfy REQ-272;  // Modular architecture requirement
        satisfy REQ-204;  // Reach radius requirement (180mm)
        satisfy REQ-302;  // X-axis travel requirement (1000mm cumulative)
    }

    part def BaseJoint :> Joint {
        attribute :>> length   = 120.0;
        attribute :>> material = "Aluminum";
    }

    part def ShoulderJoint :> Joint {
        attribute :>> length   = 220.0;
        attribute :>> material = "Aluminum";
    }

    part def ElbowJoint :> Joint {
        attribute :>> length   = 120.0;
        attribute :>> material = "Aluminum";
    }

    part def WristJoint :> Joint {
        attribute :>> length   = 80.0;
        attribute :>> material = "CarbonFiber";
    }

    part def GripperJoint :> Joint {
        attribute :>> length   = 60.0;
        attribute :>> material = "CarbonFiber";
        
        satisfy REQ-200;  // Object weight (10-500g) requirement
    }

    // ------------------------------------------------------------------
    // Controller components
    // ------------------------------------------------------------------

    abstract part def PowerSupply {
        attribute voltage : Real;   // nominal output voltage [V]
        attribute current : Real;   // max output current [A]
        attribute power   : Real;   // max power output [W]
        attribute weight  : Real;   // mass [kg]
        attribute cost    : Real;   // unit cost [USD]
        
        satisfy REQ-260;  // Power interface requirement
    }

    part def CompactPowerSupply :> PowerSupply {
        attribute :>> voltage = 12.0;
        attribute :>> current = 20.0;
        attribute :>> power   = 240.0;
        attribute :>> weight  = 0.3;
        attribute :>> cost    = 50.0;
    }

    part def StandardPowerSupply :> PowerSupply {
        attribute :>> voltage = 24.0;
        attribute :>> current = 30.0;
        attribute :>> power   = 720.0;
        attribute :>> weight  = 0.5;
        attribute :>> cost    = 120.0;
    }

    part def HighPowerSupply :> PowerSupply {
        attribute :>> voltage = 48.0;
        attribute :>> current = 50.0;
        attribute :>> power   = 2400.0;
        attribute :>> weight  = 0.8;
        attribute :>> cost    = 250.0;
    }

    abstract part def Display {
        attribute resolution  : String;  // display resolution (e.g., "128x64")
        attribute displayType : String;  // type (e.g., "LCD", "OLED", "None")
        attribute weight      : Real;    // mass [kg]
        attribute cost        : Real;    // unit cost [USD]
    }

    part def NoDisplay :> Display {
        attribute :>> displayType = "None";
        attribute :>> resolution  = "N/A";
        attribute :>> weight      = 0.0;
        attribute :>> cost        = 0.0;
    }

    part def BasicLCDDisplay :> Display {
        attribute :>> displayType = "LCD";
        attribute :>> resolution  = "128x64";
        attribute :>> weight      = 0.15;
        attribute :>> cost        = 30.0;
    }

    part def AdvancedOLEDDisplay :> Display {
        attribute :>> displayType = "OLED";
        attribute :>> resolution  = "240x128";
        attribute :>> weight      = 0.25;
        attribute :>> cost        = 80.0;
    }

    abstract part def Controller {
        part powerSupply : PowerSupply;
        part display : Display;
        attribute numServos : Integer;  // number of servos supported
        attribute totalCost : Real;     // total cost [USD]
        
        satisfy REQ-260;  // Power interface integration
    }

    part def BasicController :> Controller {
        part :>> powerSupply : CompactPowerSupply;
        part :>> display : NoDisplay;
        attribute :>> numServos = 5;
        attribute :>> totalCost = 50.0;
    }

    part def StandardController :> Controller {
        part :>> powerSupply : StandardPowerSupply;
        part :>> display : BasicLCDDisplay;
        attribute :>> numServos = 6;
        attribute :>> totalCost = 150.0;
    }

    part def AdvancedController :> Controller {
        part :>> powerSupply : HighPowerSupply;
        part :>> display : AdvancedOLEDDisplay;
        attribute :>> numServos = 7;
        attribute :>> totalCost = 330.0;
    }

    // ------------------------------------------------------------------
    // Top-level system decomposition
    // ------------------------------------------------------------------

    part def RobotArmSystem {
        part controller : StandardController;  // default to standard
        part baseJoint     : BaseJoint;
        part shoulderJoint : ShoulderJoint;
        part elbowJoint    : ElbowJoint;
        part wristJoint    : WristJoint;
        part gripperJoint  : GripperJoint;
        
        satisfy REQ-272;  // Modular architecture with 5 DOF base + gripper
    }

    // Usage-level instance of the complete system
    part robotArm : RobotArmSystem;

    // ------------------------------------------------------------------
    // Internal Block Diagram (IBD) - Mechanical & Electrical Connections
    // ------------------------------------------------------------------

    ibd def RobotArmIBD of RobotArmSystem {
        // Internal parts (implicit from RobotArmSystem definition)
        ref controller : StandardController;
        ref baseJoint : BaseJoint;
        ref shoulderJoint : ShoulderJoint;
        ref elbowJoint : ElbowJoint;
        ref wristJoint : WristJoint;
        ref gripperJoint : GripperJoint;

        // Electrical power connections from controller to all joint servos
        connection controlPower : controller.powerSupply to baseJoint.servo {
            // Power distribution from controller to base joint servo
        }
        
        connection shoulder_power : controller.powerSupply to shoulderJoint.servo {
            // Power to shoulder joint servo
        }
        
        connection elbow_power : controller.powerSupply to elbowJoint.servo {
            // Power to elbow joint servo
        }
        
        connection wrist_power : controller.powerSupply to wristJoint.servo {
            // Power to wrist joint servo
        }
        
        connection gripper_power : controller.powerSupply to gripperJoint.servo {
            // Power to gripper joint servo
        }
    }
}
