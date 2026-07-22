within ;
package RoboticArm
  "2-DOF desktop arm: shoulder + elbow pick-and-place.

   This version focuses on the two most risk-relevant joints (shoulder and
   elbow). The structure is intentionally simple and easy to extend later by
   adding more servo blocks, waypoints, and plant equations.

   Angles [deg], absolute from horizontal, CCW+:
     shoulder / elbow — arm pose in the vertical plane

   Event-driven waypoints: advance when the shoulder and elbow have settled.
   Each active joint is a stall-limited PD servo; gravity on shoulder/elbow
   uses the CAD lump masses.

   Edit: _servo_shoulder / _servo_elbow, _path_input, _mechanics_input.
  "

  // ===========================================================================
  // Inputs
  // ===========================================================================

  record ServoInput
    "One joint drive: stall limit + PD gains"
    import Modelica.Units.SI;
    SI.Torque tau_stall = 0.92 "Stall torque [N·m]";
    Real Kp(unit="N·m/rad") = 40 "Position gain [N·m/rad]";
    Real Kd(unit="N·m·s/rad") = 2.5 "Damping gain [N·m·s/rad]";
  end ServoInput;

  record ShoulderJointInput
    "Shoulder-side joint and link definition"
    import Modelica.Units.SI;

    Real position_sequence[7](each unit="deg") = {70, 50, 50, 75, 55, 55, 70}
      "Shoulder waypoint positions [deg]";
    ServoInput servo "Shoulder servo configuration";
    SI.Length link_length = 0.220 "Shoulder-to-elbow length [m]";
    SI.Mass link_mass = 0.080 "Upper-arm mass [kg]";
    SI.Mass servo_mass = 0.055 "Shoulder-side servo package mass [kg]";
    constant SI.Inertia inertia = 0.006 "Best-guess shoulder inertia [kg·m²]";
    constant Real viscous_friction(unit="N·m·s/rad") = 0.05
      "Best-guess shoulder viscous friction [N·m·s/rad]";
  end ShoulderJointInput;

  record ElbowJointInput
    "Elbow-side joint and link definition"
    import Modelica.Units.SI;

    Real position_sequence[7](each unit="deg") = {-45, -30, -30, 5, -25, -25, -45}
      "Elbow waypoint positions [deg]";
    ServoInput servo "Elbow servo configuration";
    SI.Length link_length = 0.120 "Elbow-to-tool length [m]";
    SI.Mass link_mass = 0.045 "Forearm mass [kg]";
    SI.Mass servo_mass = 0.055 "Elbow-side servo package mass [kg]";
    constant SI.Inertia inertia = 0.0015 "Best-guess elbow inertia [kg·m²]";
    constant Real viscous_friction(unit="N·m·s/rad") = 0.05
      "Best-guess elbow viscous friction [N·m·s/rad]";
  end ElbowJointInput;

  record LoadInput
    "Payload and tool proxy for the arm tip"
    import Modelica.Units.SI;

    SI.Mass proxy_mass = 0.18 "Proxy mass at the arm tip [kg]";
    SI.Length proxy_length = 0.080 "Proxy length along the forearm [m]";
    SI.Length proxy_z_offset = 0.040 "Proxy vertical offset [m]";
    Boolean carry_sequence[6] = {false, true, true, true, false, false}
      "Carry-load flag for each waypoint stage";
  end LoadInput;

  // ===========================================================================
  // Plant
  // ===========================================================================

  model PositionServo
    "PD servo with ±stall saturation; command in deg"
    import Modelica.Units.SI;
    import Modelica.Units.Conversions.from_deg;

    parameter SI.Torque tau_stall = 0.92 annotation (HideResult=true);
    parameter Real Kp(unit="N·m/rad") = 40 annotation (HideResult=true);
    parameter Real Kd(unit="N·m·s/rad") = 2.5 annotation (HideResult=true);

    Modelica.Blocks.Interfaces.RealInput position_command(unit="deg")
      annotation (HideResult=true);
    Modelica.Mechanics.Rotational.Interfaces.Flange_a flange
      annotation (HideResult=true);
    SI.Torque torque_output annotation (HideResult=true);
  protected
    SI.Angle q = flange.phi;
    SI.AngularVelocity w = der(q);
    SI.Torque tau_cmd = Kp * (from_deg(position_command) - q) - Kd * w;
  equation
    torque_output = smooth(0, noEvent(
      if tau_cmd > tau_stall then tau_stall
      elseif tau_cmd < -tau_stall then -tau_stall
      else tau_cmd));
    flange.tau = -torque_output;
  end PositionServo;

  model ArmPlant
    "Planar 2-link arm with a placeholder for future optional joints."
    import Modelica.Units.SI;
    import Modelica.Constants.g_n;
    import Modelica.Units.Conversions.from_deg;

    parameter ShoulderJointInput shoulder_input annotation (HideResult=true);
    parameter ElbowJointInput elbow_input annotation (HideResult=true);
    parameter LoadInput load_input annotation (HideResult=true);
    parameter Real th1_0(unit="deg") = 70 annotation (HideResult=true);
    parameter Real th2_0(unit="deg") = -45 annotation (HideResult=true);

    Modelica.Blocks.Interfaces.RealInput payload_mass(unit="kg")
      annotation (HideResult=true);
    Modelica.Blocks.Interfaces.BooleanInput carrying
      annotation (HideResult=true);
    Modelica.Mechanics.Rotational.Interfaces.Flange_a flange_shoulder
      annotation (HideResult=true);
    Modelica.Mechanics.Rotational.Interfaces.Flange_a flange_elbow
      annotation (HideResult=true);
    SI.Angle th1(start=from_deg(th1_0), fixed=true) annotation (HideResult=true);
    SI.Angle th2(start=from_deg(th2_0), fixed=true) annotation (HideResult=true);
    SI.AngularVelocity w1(start=0, fixed=true) annotation (HideResult=true);
    SI.AngularVelocity w2(start=0, fixed=true) annotation (HideResult=true);
    SI.Torque tau_grav_sh annotation (HideResult=true);
    SI.Torque tau_grav_el annotation (HideResult=true);
  protected
    SI.Length x_p2 = shoulder_input.link_length * cos(th1);
    SI.Length x_fa = x_p2 + (elbow_input.link_length / 2) * cos(th2);
    SI.Length x_p3 = x_p2 + elbow_input.link_length * cos(th2);
    // forearm-frame (x,z) → horizontal lever at elbow angle th2
    SI.Length x_grip = x_p3 + load_input.proxy_length * cos(th2) - load_input.proxy_z_offset * sin(th2);
    SI.Length x_pay = x_p3 + load_input.proxy_length * cos(th2) - load_input.proxy_z_offset * sin(th2);

    SI.Inertia J1 = shoulder_input.inertia
                    + shoulder_input.link_mass * (shoulder_input.link_length / 2) ^ 2
                    + shoulder_input.servo_mass * shoulder_input.link_length ^ 2
                    + elbow_input.link_mass * (shoulder_input.link_length + elbow_input.link_length / 2) ^ 2
                    + load_input.proxy_mass * (shoulder_input.link_length + elbow_input.link_length + load_input.proxy_length) ^ 2
                    + payload_mass * (shoulder_input.link_length + elbow_input.link_length + load_input.proxy_length) ^ 2;
    SI.Inertia J2 = elbow_input.inertia
                    + elbow_input.link_mass * (elbow_input.link_length / 2) ^ 2
                    + load_input.proxy_mass * (elbow_input.link_length + load_input.proxy_length) ^ 2
                    + payload_mass * (elbow_input.link_length + load_input.proxy_length) ^ 2;
  equation
    th1 = flange_shoulder.phi;
    th2 = flange_elbow.phi;
    w1 = der(th1);
    w2 = der(th2);

    tau_grav_sh = g_n * (
      shoulder_input.link_mass * (shoulder_input.link_length / 2) * cos(th1)
      + shoulder_input.servo_mass * x_p2
      + elbow_input.link_mass * x_fa
      + load_input.proxy_mass * x_grip
      + payload_mass * x_pay);
    tau_grav_el = g_n * (
      elbow_input.link_mass * (x_fa - x_p2)
      + load_input.proxy_mass * (x_grip - x_p2)
      + payload_mass * (x_pay - x_p2));

    J1 * der(w1) = flange_shoulder.tau - tau_grav_sh - shoulder_input.viscous_friction * w1;
    J2 * der(w2) = flange_elbow.tau - tau_grav_el - elbow_input.viscous_friction * w2;
  end ArmPlant;

  // ===========================================================================
  // Experiment
  // ===========================================================================

  model RoboticArmSimulation
    "Feasible pick-and-place; results expose move_time for servo sweeps."
    import Modelica.Units.SI;
    import Modelica.Constants.pi;

    // Defaults = a representative two-joint sweep configuration:
    //   shoulder MG996R, elbow DS5160
    parameter ShoulderJointInput _shoulder_input(
      servo(tau_stall=0.92),
      position_sequence={70, 50, 50, 75, 55, 55, 70})
      "Shoulder joint input" annotation (Dialog);
    parameter ElbowJointInput _elbow_input(
      servo(tau_stall=5.88),
      position_sequence={-45, -30, -30, 5, -25, -25, -45})
      "Elbow joint input" annotation (Dialog);
    parameter LoadInput _load_input annotation (Dialog);

    // Swept quantities as top-level scalars: runtime -override of record
    // members is unreliable (records are evaluated at build time), so the
    // sweep scripts override these instead.
    parameter SI.Torque tau_stall_shoulder = _shoulder_input.servo.tau_stall
      "Shoulder servo stall torque [N·m]" annotation (Evaluate=false);
    parameter SI.Torque tau_stall_elbow = _elbow_input.servo.tau_stall
      "Elbow servo stall torque [N·m]" annotation (Evaluate=false);

    PositionServo servo_sh(
      tau_stall=tau_stall_shoulder,
      Kp=_shoulder_input.servo.Kp,
      Kd=_shoulder_input.servo.Kd) annotation (HideResult=true);
    PositionServo servo_el(
      tau_stall=tau_stall_elbow,
      Kp=_elbow_input.servo.Kp,
      Kd=_elbow_input.servo.Kd) annotation (HideResult=true);
    ArmPlant plant(
      shoulder_input=_shoulder_input,
      elbow_input=_elbow_input,
      load_input=_load_input,
      th1_0=_shoulder_input.position_sequence[1],
      th2_0=_elbow_input.position_sequence[1]) annotation (HideResult=true);

    // --- plot / harvest ------------------------------------------------------
    Real shoulder_set(unit="deg") "Shoulder command [deg]";
    Real elbow_set(unit="deg") "Elbow command [deg]";
    Real shoulder_act(unit="deg") "Shoulder actual [deg]";
    Real elbow_act(unit="deg") "Elbow actual [deg]";
    SI.Torque tau_shoulder "Shoulder servo torque [N·m]";
    SI.Torque tau_elbow "Elbow servo torque [N·m]";
    SI.Time move_time
      "Seconds when the last waypoint was reached (0 if unfinished)";

  protected
    Integer current_stage(start=1, fixed=true) "1..6 → p1..p6; 7 = done";
    discrete SI.Time finished_time(start=0, fixed=true);
    Boolean carrying(start=_load_input.carry_sequence[1], fixed=true);
    Boolean enable_arrive(start=false, fixed=true);
    SI.Mass payload_mass_kg;

    Real target_shoulder(unit="deg");
    Real target_elbow(unit="deg");
    Real shoulder_cmd(unit="deg", start=_shoulder_input.position_sequence[1], fixed=true);
    Real elbow_cmd(unit="deg", start=_elbow_input.position_sequence[1], fixed=true);

    Boolean at_shoulder;
    Boolean at_elbow;
    Boolean slow_shoulder;
    Boolean slow_elbow;
    Boolean arrived;

    function twoJointWaypointSelect
      input Integer s;
      input ShoulderJointInput shoulder_input;
      input ElbowJointInput elbow_input;
      output Real sh;
      output Real el;
    algorithm
      if s <= 1 then
        sh := shoulder_input.position_sequence[2]; el := elbow_input.position_sequence[2];
      elseif s == 2 then
        sh := shoulder_input.position_sequence[3]; el := elbow_input.position_sequence[3];
      elseif s == 3 then
        sh := shoulder_input.position_sequence[4]; el := elbow_input.position_sequence[4];
      elseif s == 4 then
        sh := shoulder_input.position_sequence[5]; el := elbow_input.position_sequence[5];
      elseif s == 5 then
        sh := shoulder_input.position_sequence[6]; el := elbow_input.position_sequence[6];
      else
        sh := shoulder_input.position_sequence[7]; el := elbow_input.position_sequence[7];
      end if;
    end twoJointWaypointSelect;

  equation
    connect(servo_sh.flange, plant.flange_shoulder);
    connect(servo_el.flange, plant.flange_elbow);

    servo_sh.position_command = shoulder_set;
    servo_el.position_command = elbow_set;
    plant.payload_mass = payload_mass_kg;
    plant.carrying = carrying;
    payload_mass_kg = if carrying then _load_input.proxy_mass else 0;

    // pre() breaks the algebraic event loop stage -> target -> arrived -> stage,
    // which OpenModelica would otherwise turn into an (unsupported) mixed
    // nonlinear system.
    (target_shoulder, target_elbow) = twoJointWaypointSelect(pre(current_stage), _shoulder_input, _elbow_input);

    der(shoulder_cmd) = noEvent(if abs(shoulder_cmd - target_shoulder) < 1e-4 then 0
                                else -600 * sign(shoulder_cmd - target_shoulder));
    der(elbow_cmd) = noEvent(if abs(elbow_cmd - target_elbow) < 1e-4 then 0
                             else -600 * sign(elbow_cmd - target_elbow));

    shoulder_set = shoulder_cmd;
    elbow_set = elbow_cmd;
    shoulder_act = (180 / pi) * plant.th1;
    elbow_act = (180 / pi) * plant.th2;
    tau_shoulder = servo_sh.torque_output;
    tau_elbow = servo_el.torque_output;
    move_time = finished_time;

    at_shoulder = abs(shoulder_act - target_shoulder) < 2.5;
    at_elbow = abs(elbow_act - target_elbow) < 2.5;
    slow_shoulder = abs(der(shoulder_act)) < 12.0;
    slow_elbow = abs(der(elbow_act)) < 12.0;
    arrived = at_shoulder and at_elbow and slow_shoulder and slow_elbow;

  algorithm
    // Stage machine as an algorithm: equation-form when-clauses here end up in
    // a nonlinear system (condition depends on variables assigned in the body),
    // which OpenModelica cannot lower.
    when time > 0 then
      enable_arrive := true;
    end when;

    when enable_arrive and arrived and pre(current_stage) < 7 then
      if pre(current_stage) == 6 then
        finished_time := time;
      end if;
      carrying := _load_input.carry_sequence[pre(current_stage)];
      current_stage := pre(current_stage) + 1;
    end when;

    annotation (experiment(
        StartTime=0,
        StopTime=15,
        Tolerance=1e-6,
        Interval=0.02));
  end RoboticArmSimulation;

  annotation (uses(Modelica(version="4.0.0")));
end RoboticArm;
