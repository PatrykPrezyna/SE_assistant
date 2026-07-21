within ;

package ElbowServo

  "1-DOF elbow servo: position command in deg, gravity load, stall limit.



   Angle convention (absolute from horizontal, CCW positive):

     −45° = tip on the ground (start / place pose)

       0° = forearm horizontal

     Shoulder is held fixed at +45° in this experiment.



   Edit knobs in OMEdit under:

     _servo_input      — stall torque and PD gains

     _path_input       — start pose, waypoints, move duration

     _mechanics_input  — arm / gripper / payload masses and lengths

  "



  // ===========================================================================

  // Input structures (shown in the OMEdit parameter dialog)

  // ===========================================================================



  record Waypoint

    "One target pose on the pick-and-place path"

    import Modelica.Units.SI;

    SI.Time t_start = 0

      "Wall-clock time when the move toward this pose starts [s]";

    Real theta(unit="deg") = 0

      "Target elbow angle for this pose [deg]";

    Boolean carry_load = false

      "If true, payload is attached after this pose is reached";

  end Waypoint;



  record ServoInput

    "Elbow servo drive: stall limit and PD position loop"

    import Modelica.Units.SI;

    SI.Torque tau_stall = 0.196

      "Maximum torque the servo can deliver [N·m] (AD002 ≈ 2.0 kg·cm)";

    Real Kp(unit="N·m/rad") = 50

      "Proportional gain of the position loop [N·m/rad]";

    Real Kd(unit="N·m·s/rad") = 3.0

      "Derivative (damping) gain of the position loop [N·m·s/rad]";

  end ServoInput;



  record PathInput

    "Motion profile: start pose plus four follow waypoints"

    import Modelica.Units.SI;



    SI.Time t_move = 1.5

      "Duration of every move between consecutive poses [s]";

    Real theta0(unit="deg") = -45

      "Elbow angle at simulation start [deg]";

    Boolean carry0 = false

      "True if the payload is already held at t = 0";



    // Four follow poses (edit modifiers in place; fixed size keeps the dialog simple)

    Waypoint p1(t_start=0,   theta=0,   carry_load=false)

      "1: raise empty arm to horizontal";

    Waypoint p2(t_start=2.5, theta=-45, carry_load=true)

      "2: lower to ground and pick up the object";

    Waypoint p3(t_start=4.5, theta=0,   carry_load=true)

      "3: raise arm while carrying the object";

    Waypoint p4(t_start=7.0, theta=-45, carry_load=false)

      "4: lower to ground and release the object";

  end PathInput;



  record MechanicsInput

    "Rigid-body masses and lever arms about the elbow.



     Default lumps match the CAD-derived values in torque_analysis.py.

    "

    import Modelica.Units.SI;



    SI.Length L_forearm = 0.05

      "Forearm length from elbow pivot to wrist [m]";

    SI.Mass m_forearm = 0.082

      "Forearm mass (pair of acrylic side plates) [kg]";

    SI.Mass m_gripper = 0.167

      "Gripper cluster mass (housing, gears, fingers) [kg]";

    SI.Length r_gripper = 0.047

      "Gripper center-of-mass distance past the wrist [m]";

    SI.Mass m_load = 0.01

      "Picked-object mass while carry_load is true [kg]";

    SI.Length r_payload = 0.115

      "Object attach point distance past the wrist (fingertip) [m]";

    SI.Inertia J_extra = 0.002

      "Additional rotary inertia about the elbow (unmodeled parts) [kg·m²]";

    Real b(unit="N·m·s/rad") = 0.05

      "Viscous friction coefficient at the elbow joint [N·m·s/rad]";

  end MechanicsInput;



  // ===========================================================================

  // Trajectory helpers

  // ===========================================================================



  function blendTo

    "Smooth min-jerk blend from theta0 to theta1 over [t0, t0+t_move], then hold.



     Min-jerk (5th-order) keeps speed and acceleration zero at both ends,

     which is a reasonable stand-in for a gentle servo motion profile.

    "

    input Real t "Current time [s]";

    input Real t0 "Move start time [s]";

    input Real t_move "Move duration [s]";

    input Real theta0 "Angle at start of move [deg]";

    input Real theta1 "Angle at end of move [deg]";

    output Real theta "Blended angle command [deg]";

  protected

    Real u "Normalized time in [0, 1] during the move";

    Real s "Min-jerk interpolation weight in [0, 1]";

  algorithm

    if t <= t0 then

      theta := theta0;

    elseif t >= t0 + t_move then

      theta := theta1;

    else

      u := max(0, min(1, (t - t0) / t_move));

      s := 10 * u ^ 3 - 15 * u ^ 4 + 6 * u ^ 5;

      theta := theta0 + (theta1 - theta0) * s;

    end if;

  end blendTo;



  function pathTheta

    "Elbow position command [deg] along start → p1 → p2 → p3 → p4"

    input Real t;

    input PathInput p;

    output Real theta;

  algorithm

    theta := if t < p.p1.t_start then

               p.theta0

             elseif t < p.p2.t_start then

               blendTo(t, p.p1.t_start, p.t_move, p.theta0, p.p1.theta)

             elseif t < p.p3.t_start then

               blendTo(t, p.p2.t_start, p.t_move, p.p1.theta, p.p2.theta)

             elseif t < p.p4.t_start then

               blendTo(t, p.p3.t_start, p.t_move, p.p2.theta, p.p3.theta)

             else

               blendTo(t, p.p4.t_start, p.t_move, p.p3.theta, p.p4.theta);

  end pathTheta;



  function pathCarry

    "Carried payload mass [kg]. Switches at move completion (t_start + t_move)."

    input Real t;

    input PathInput p;

    input Real m_load;

    output Real m;

  protected

    Real a1 = p.p1.t_start + p.t_move;

    Real a2 = p.p2.t_start + p.t_move;

    Real a3 = p.p3.t_start + p.t_move;

    Real a4 = p.p4.t_start + p.t_move;

  algorithm

    m := m_load * (if t < a1 then (if p.carry0 then 1 else 0)

                   elseif t < a2 then (if p.p1.carry_load then 1 else 0)

                   elseif t < a3 then (if p.p2.carry_load then 1 else 0)

                   elseif t < a4 then (if p.p3.carry_load then 1 else 0)

                   else (if p.p4.carry_load then 1 else 0));

  end pathCarry;



  // ===========================================================================

  // Plant models (results hidden — plot the numbered outputs on the experiment)

  // ===========================================================================



  model PositionServo

    "PD position servo with symmetric stall-torque saturation.



     Command is in degrees; internal loop works in radians.

     Output torque is clamped to ±tau_stall (datasheet stall).

    "

    import Modelica.Units.SI;

    import Modelica.Units.Conversions.from_deg;



    parameter SI.Torque tau_stall = 0.196

      "Stall torque limit [N·m]" annotation (HideResult=true);

    parameter Real Kp(unit="N·m/rad") = 50

      "Position gain [N·m/rad]" annotation (HideResult=true);

    parameter Real Kd(unit="N·m·s/rad") = 3.0

      "Damping gain [N·m·s/rad]" annotation (HideResult=true);



    Modelica.Blocks.Interfaces.RealInput position_command(unit="deg")

      "Requested elbow angle [deg]" annotation (HideResult=true);

    Modelica.Mechanics.Rotational.Interfaces.Flange_a flange

      "Mechanical connection to the forearm" annotation (HideResult=true);



    SI.Torque torque_output

      "Torque delivered to the load after stall limiting [N·m]"

      annotation (HideResult=true);

  protected

    SI.Angle position_rad = flange.phi;

    SI.AngularVelocity velocity_rad = der(position_rad);

    // Unlimited PD command, then saturated to the servo stall rating

    SI.Torque torque_command =

      Kp * (from_deg(position_command) - position_rad) - Kd * velocity_rad;

  equation

    torque_output = smooth(0, noEvent(

      if torque_command > tau_stall then tau_stall

      elseif torque_command < -tau_stall then -tau_stall

      else torque_command));

    flange.tau = -torque_output;

  end PositionServo;



  model ForearmLoad

    "Rotating forearm + gripper + optional payload about the elbow.



     Dynamics: J*α = τ_servo − τ_gravity − b*ω

     Gravity torque uses the combined center of mass; payload mass is an input

     so pick/place can attach or release the object during the run.

    "

    import Modelica.Units.SI;

    import Modelica.Constants.g_n;



    parameter SI.Length L_forearm = 0.05 annotation (HideResult=true);

    parameter SI.Mass m_forearm = 0.082 annotation (HideResult=true);

    parameter SI.Mass m_gripper = 0.167 annotation (HideResult=true);

    parameter SI.Length r_gripper = 0.047 annotation (HideResult=true);

    parameter SI.Length r_payload = 0.115 annotation (HideResult=true);

    parameter SI.Inertia J_extra = 0.002 annotation (HideResult=true);

    parameter Real b(unit="N·m·s/rad") = 0.05 annotation (HideResult=true);



    Modelica.Blocks.Interfaces.RealInput payload_mass(unit="kg")

      "Attached object mass; 0 when empty [kg]" annotation (HideResult=true);

    Modelica.Mechanics.Rotational.Interfaces.Flange_a flange

      "Elbow flange (driven by the servo)" annotation (HideResult=true);



    SI.Angle position_rad

      "Elbow angle [rad]" annotation (HideResult=true);

    SI.Torque gravity_torque

      "Gravity load torque about the elbow [N·m]" annotation (HideResult=true);

  protected

    SI.Mass mass_total = m_forearm + m_gripper + payload_mass;

    SI.Length com_radius = (m_forearm * (L_forearm / 2)

                            + m_gripper * (L_forearm + r_gripper)

                            + payload_mass * (L_forearm + r_payload)) / mass_total;

    // Point-mass inertias about the elbow plus a small unmodeled remainder

    SI.Inertia inertia = J_extra

                         + m_forearm * (L_forearm / 2) ^ 2

                         + m_gripper * (L_forearm + r_gripper) ^ 2

                         + payload_mass * (L_forearm + r_payload) ^ 2;

    SI.AngularVelocity velocity_rad = der(position_rad);

  equation

    position_rad = flange.phi;

    // cos(theta): torque peaks when the forearm is horizontal

    gravity_torque = mass_total * g_n * com_radius * cos(position_rad);

    inertia * der(velocity_rad) = flange.tau - gravity_torque - b * velocity_rad;

  end ForearmLoad;



  // ===========================================================================

  // Experiment

  // ===========================================================================



  model ElbowServoSimulation

    "Ground pick-and-place with a torque-limited elbow servo.



     Variable browser (top level):

       _servo_input / _path_input / _mechanics_input  — editable parameters

       1_set_position … 5_actual_torque               — signals to plot

     (servo/forearm internals are hidden)

    "

    import Modelica.Units.SI;

    import Modelica.Units.Conversions.from_deg;

    import Modelica.Constants.pi;



    // --- Parameter groups (kept visible in the simulation window) -------------

    parameter ServoInput _servo_input annotation (Dialog);

    parameter PathInput _path_input annotation (Dialog);

    parameter MechanicsInput _mechanics_input annotation (Dialog);



    // Hidden plant; plot the numbered aliases below instead

    PositionServo servo(

      tau_stall=_servo_input.tau_stall,

      Kp=_servo_input.Kp,

      Kd=_servo_input.Kd) annotation (HideResult=true);

    ForearmLoad forearm(

      L_forearm=_mechanics_input.L_forearm,

      m_forearm=_mechanics_input.m_forearm,

      m_gripper=_mechanics_input.m_gripper,

      r_gripper=_mechanics_input.r_gripper,

      r_payload=_mechanics_input.r_payload,

      J_extra=_mechanics_input.J_extra,

      b=_mechanics_input.b) annotation (HideResult=true);



    // --- Plot signals (quoted names so they sort 1…5 in OMEdit) --------------

    Real '1_set_position'(unit="deg")

      "1) Set position — commanded elbow angle [deg]";

    Real '2_actual_position'(unit="deg")

      "2) Actual position — measured elbow angle [deg]";

    Real '3_set_speed'(unit="deg/s")

      "3) Set speed — commanded angular velocity [deg/s]";

    Real '4_actual_speed'(unit="deg/s")

      "4) Actual speed — measured angular velocity [deg/s]";

    SI.Torque '5_actual_torque'

      "5) Actual torque — servo output after stall limiting [N·m]";



  protected

    SI.Mass payload_mass_kg

      "Internal: payload attached to the forearm this instant [kg]";



  initial equation

    forearm.position_rad = from_deg(_path_input.theta0);

    der(forearm.position_rad) = 0;



  equation

    connect(servo.flange, forearm.flange);



    servo.position_command = '1_set_position';

    forearm.payload_mass = payload_mass_kg;



    '1_set_position' = noEvent(pathTheta(time, _path_input));

    payload_mass_kg = noEvent(

      pathCarry(time, _path_input, _mechanics_input.m_load));



    '2_actual_position' = (180 / pi) * forearm.position_rad;

    '3_set_speed' = der('1_set_position');

    '4_actual_speed' = der('2_actual_position');

    '5_actual_torque' = servo.torque_output;



    annotation (experiment(

        StartTime=0,

        StopTime=10,

        Tolerance=1e-6,

        Interval=0.01));

  end ElbowServoSimulation;



  annotation (uses(Modelica(version="4.0.0")));

end ElbowServo;


