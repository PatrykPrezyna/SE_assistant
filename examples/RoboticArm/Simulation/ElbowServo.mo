package ElbowServo "1-DOF elbow servo: position command in deg, gravity load, stall limit.

   Angle convention (absolute from horizontal, CCW positive):
     −45° = tip on the ground (start / place pose)
       0° = forearm horizontal
     Shoulder is held fixed at +45° in this experiment.

   Motion: as soon as a waypoint is reached (position + speed tolerances),
   the next target is selected. The position command slews toward it at
   max_speed (stall-limited PD tracks as hard as the servo allows).

   Edit knobs in OMEdit under:
     _servo_input      — stall torque and PD gains
     _path_input       — poses, max_speed, arrival tolerances
     _mechanics_input  — arm / gripper / payload masses and lengths
  "
  // ===========================================================================
  // Input structures (shown in the OMEdit parameter dialog)
  // ===========================================================================

  record Waypoint "One target pose on the pick-and-place path"
    Real theta(unit = "deg") = 0 "Target elbow angle for this pose [deg]";
    Boolean carry_load = false "If true, payload is attached after this pose is reached";
  end Waypoint;

  record ServoInput "Elbow servo drive: stall limit and PD position loop"
    import Modelica.Units.SI;
    SI.Torque tau_stall = 0.196 "Maximum torque the servo can deliver [N·m] (AD002 ≈ 2.0 kg·cm)";
    Real Kp(unit = "N·m/rad") = 50 "Proportional gain of the position loop [N·m/rad]";
    Real Kd(unit = "N·m·s/rad") = 3.0 "Derivative (damping) gain of the position loop [N·m·s/rad]";
  end ServoInput;

  record PathInput "Sequential poses: advance on arrival, slew at max_speed"
    Real theta0(unit = "deg") = -45 "Elbow angle at simulation start [deg]";
    Boolean carry0 = false "True if the payload is already held at t = 0";
    Real max_speed(unit = "deg/s") = 180 "Command slew rate toward the active waypoint — raise to go faster [deg/s]";
    Real arrive_tol(unit = "deg") = 1.5 "Position tolerance to declare a waypoint reached [deg]";
    Real settle_speed(unit = "deg/s") = 8.0 "Actual speed must be below this to advance [deg/s]";
    Waypoint p1(theta = 0, carry_load = false) "1: raise empty arm to horizontal";
    Waypoint p2(theta = -45, carry_load = true) "2: lower to ground and pick up the object";
    Waypoint p3(theta = 0, carry_load = true) "3: raise arm while carrying the object";
    Waypoint p4(theta = -45, carry_load = false) "4: lower to ground and release the object";
  end PathInput;

  record MechanicsInput "Rigid-body masses and lever arms about the elbow.

       Default lumps match the CAD-derived values in torque_analysis.py.
      "
    import Modelica.Units.SI;
    SI.Length L_forearm = 0.05 "Forearm length from elbow pivot to wrist [m]";
    SI.Mass m_forearm = 0.082 "Forearm mass (pair of acrylic side plates) [kg]";
    SI.Mass m_gripper = 0.167 "Gripper cluster mass (housing, gears, fingers) [kg]";
    SI.Length r_gripper = 0.047 "Gripper center-of-mass distance past the wrist [m]";
    SI.Mass m_load = 0.01 "Picked-object mass while carry_load is true [kg]";
    SI.Length r_payload = 0.115 "Object attach point distance past the wrist (fingertip) [m]";
    SI.Inertia J_extra = 0.002 "Additional rotary inertia about the elbow (unmodeled parts) [kg·m²]";
    Real b(unit = "N·m·s/rad") = 0.05 "Viscous friction coefficient at the elbow joint [N·m·s/rad]";
  end MechanicsInput;

  // ===========================================================================
  // Plant models (results hidden — plot the numbered outputs on the experiment)
  // ===========================================================================

  model PositionServo "PD position servo with symmetric stall-torque saturation.

       Command is in degrees; internal loop works in radians.
       Output torque is clamped to ±tau_stall (datasheet stall).
      "
    import Modelica.Units.SI;
    import Modelica.Units.Conversions.from_deg;
    parameter SI.Torque tau_stall = 5.88 "Stall torque limit [N·m]" annotation(
      HideResult = true);
    parameter Real Kp(unit = "N·m/rad") = 50 "Position gain [N·m/rad]" annotation(
      HideResult = true);
    parameter Real Kd(unit = "N·m·s/rad") = 3.0 "Damping gain [N·m·s/rad]" annotation(
      HideResult = true);
    Modelica.Blocks.Interfaces.RealInput position_command(unit = "deg") "Requested elbow angle [deg]" annotation(
      HideResult = true);
    Modelica.Mechanics.Rotational.Interfaces.Flange_a flange "Mechanical connection to the forearm" annotation(
      HideResult = true);
    SI.Torque torque_output "Torque delivered to the load after stall limiting [N·m]" annotation(
      HideResult = true);
  protected
    SI.Angle position_rad = flange.phi;
    SI.AngularVelocity velocity_rad = der(position_rad);
    SI.Torque torque_command = Kp*(from_deg(position_command) - position_rad) - Kd*velocity_rad;
  equation
    torque_output = smooth(0, noEvent(if torque_command > tau_stall then tau_stall elseif torque_command < -tau_stall then -tau_stall else torque_command));
    flange.tau = -torque_output;
  end PositionServo;

  model ForearmLoad "Rotating forearm + gripper + optional payload about the elbow.

       Dynamics: J*α = τ_servo − τ_gravity − b*ω
      "
    import Modelica.Units.SI;
    import Modelica.Constants.g_n;
    import Modelica.Units.Conversions.from_deg;
    parameter SI.Length L_forearm = 0.05 annotation(
      HideResult = true);
    parameter SI.Mass m_forearm = 0.082 annotation(
      HideResult = true);
    parameter SI.Mass m_gripper = 0.167 annotation(
      HideResult = true);
    parameter SI.Length r_gripper = 0.047 annotation(
      HideResult = true);
    parameter SI.Length r_payload = 0.115 annotation(
      HideResult = true);
    parameter SI.Inertia J_extra = 0.002 annotation(
      HideResult = true);
    parameter Real b(unit = "N·m·s/rad") = 0.05 annotation(
      HideResult = true);
    parameter Real theta0_deg(unit = "deg") = -45 "Initial elbow angle [deg]" annotation(
      HideResult = true);
    Modelica.Blocks.Interfaces.RealInput payload_mass(unit = "kg") "Attached object mass; 0 when empty [kg]" annotation(
      HideResult = true);
    Modelica.Mechanics.Rotational.Interfaces.Flange_a flange "Elbow flange (driven by the servo)" annotation(
      HideResult = true);
    SI.Angle position_rad(start = from_deg(theta0_deg), fixed = true) "Elbow angle [rad]" annotation(
      HideResult = true);
    SI.AngularVelocity velocity_rad(start = 0, fixed = true) "Elbow angular velocity [rad/s]" annotation(
      HideResult = true);
    SI.Torque gravity_torque "Gravity load torque about the elbow [N·m]" annotation(
      HideResult = true);
  protected
    SI.Mass mass_total = m_forearm + m_gripper + payload_mass;
    SI.Length com_radius = (m_forearm*(L_forearm/2) + m_gripper*(L_forearm + r_gripper) + payload_mass*(L_forearm + r_payload))/mass_total;
    SI.Inertia inertia = J_extra + m_forearm*(L_forearm/2)^2 + m_gripper*(L_forearm + r_gripper)^2 + payload_mass*(L_forearm + r_payload)^2;
  equation
    position_rad = flange.phi;
    velocity_rad = der(position_rad);
    gravity_torque = mass_total*g_n*com_radius*cos(position_rad);
    inertia*der(velocity_rad) = flange.tau - gravity_torque - b*velocity_rad;
  end ForearmLoad;

  // ===========================================================================
  // Experiment
  // ===========================================================================

  model ElbowServoSimulation "Ground pick-and-place with a torque-limited elbow servo.

       Event-driven waypoints: on arrival, immediately select the next pose.
       Position command slews at max_speed (no timed dwells).

       Variable browser (top level):
         _servo_input / _path_input / _mechanics_input  — editable parameters
         1_set_position … 6_move_time                 — signals to plot
      "
    import Modelica.Units.SI;
    import Modelica.Constants.pi;
    parameter ServoInput _servo_input annotation(
      Dialog);
    parameter PathInput _path_input annotation(
      Dialog);
    parameter MechanicsInput _mechanics_input annotation(
      Dialog);
    PositionServo servo(tau_stall = _servo_input.tau_stall, Kp = _servo_input.Kp, Kd = _servo_input.Kd) annotation(
      HideResult = true);
    ForearmLoad forearm(L_forearm = _mechanics_input.L_forearm, m_forearm = _mechanics_input.m_forearm, m_gripper = _mechanics_input.m_gripper, r_gripper = _mechanics_input.r_gripper, r_payload = _mechanics_input.r_payload, J_extra = _mechanics_input.J_extra, b = _mechanics_input.b, theta0_deg = _path_input.theta0) annotation(
      HideResult = true);
    // --- Plot signals --------------------------------------------------------
    Real '1_set_position'(unit = "deg") "1) Set position — commanded elbow angle [deg]";
    Real '2_actual_position'(unit = "deg") "2) Actual position — measured elbow angle [deg]";
    Real '3_set_speed'(unit = "deg/s") "3) Set speed — command slew rate [deg/s]";
    Real '4_actual_speed'(unit = "deg/s") "4) Actual speed — measured angular velocity [deg/s]";
    SI.Torque '5_actual_torque' "5) Actual torque — servo output after stall limiting [N·m]";
    SI.Time '6_move_time' "6) Move time — seconds when the last waypoint was reached (0 if unfinished)";
  protected
    // stage = 1..4 → going to p1..p4; stage = 5 → finished, hold last pose
    Integer stage(start = 1, fixed = true);
    discrete SI.Time t_finished(start = 0, fixed = true)
      "Wall time at which stage advanced past p4";
    Boolean carrying(start = _path_input.carry0, fixed = true);
    // Inhibit arrival at t=0 so we don't "reach" a pose we haven't moved to
    Boolean enable_arrive(start = false, fixed = true);
    SI.Mass payload_mass_kg;
    Real target_pos(unit = "deg") "Active waypoint angle [deg]";
    Real command_pos(unit = "deg", start = _path_input.theta0, fixed = true) "Slew-limited position command fed to the servo [deg]";
    Real command_speed(unit = "deg/s") "d(command_pos)/dt [deg/s]";
    Real pos_err(unit = "deg") "command_pos − target_pos [deg]";
    Boolean at_target "Actual angle within arrive_tol of the active waypoint";
    Boolean nearly_stopped "Actual speed below settle_speed";
  equation
    connect(servo.flange, forearm.flange);
    servo.position_command = '1_set_position';
    forearm.payload_mass = payload_mass_kg;
    payload_mass_kg = if carrying then _mechanics_input.m_load else 0;
    target_pos = if stage <= 1 then _path_input.p1.theta elseif stage == 2 then _path_input.p2.theta
     elseif stage == 3 then _path_input.p3.theta else _path_input.p4.theta;
// Full-speed slew toward the active target
    pos_err = command_pos - target_pos;
    command_speed = noEvent(if abs(pos_err) < 1e-4 then 0 else -_path_input.max_speed*sign(pos_err));
    der(command_pos) = command_speed;
    '1_set_position' = command_pos;
    '2_actual_position' = (180/pi)*forearm.position_rad;
    '3_set_speed' = command_speed;
    '4_actual_speed' = (180/pi)*forearm.velocity_rad;
    '5_actual_torque' = servo.torque_output;
    '6_move_time' = t_finished;
    at_target = abs('2_actual_position' - target_pos) < _path_input.arrive_tol;
    nearly_stopped = abs('4_actual_speed') < _path_input.settle_speed;
// Skip the initial instant; then advance as soon as each pose is settled
    when time > 0 then
      enable_arrive = true;
    end when;
    when enable_arrive and at_target and nearly_stopped and pre(stage) < 5 then
      carrying = if pre(stage) == 1 then _path_input.p1.carry_load elseif pre(stage) == 2 then _path_input.p2.carry_load
       elseif pre(stage) == 3 then _path_input.p3.carry_load else _path_input.p4.carry_load;
      // pre(stage)==4 → just reached the last destination (p4)
      t_finished = if pre(stage) == 4 then time else pre(t_finished);
      stage = pre(stage) + 1;
    end when;
    annotation(
      experiment(StartTime = 0, StopTime = 10, Tolerance = 1e-6, Interval = 0.01));
  end ElbowServoSimulation;
  annotation(
    uses(Modelica(version = "4.0.0")));
end ElbowServo;
