package CoolSpineSystemContext {

    // Load after CoolSpineRequirements + CoolSpineSystem (name-sorted order).
    private import ScalarValues::*;
    private import CoolSpineSystem::*;

    // ------------------------------------------------------------------
    // People in the OR
    // ------------------------------------------------------------------

    part def Patient {
        doc /*
        Person receiving cooling. The CoolSpine catheter is the heat-exchange
        path in the patient. A separate CSF drain may be used for pressure /
        drainage monitoring (not part of the CoolSpine fluid loop).
        */
    }

    part def Surgeon {
        doc /*
        Lead clinician for the procedure. Decides whether to use CoolSpine and
        may ask for changes to cooling or flow; does not usually drive the
        device UI (that is the anesthesiologist).
        */
    }

    part def Anesthesiologist {
        doc /*
        Clinician who watches patient physiology and is the main operator of
        CoolSpine (power on, setpoints, stop) during the case.
        */
    }

    // ------------------------------------------------------------------
    // Optional CSF drain (hospital equipment next to CoolSpine)
    // ------------------------------------------------------------------

    part def PressureSensor {
        doc /*
        Measures CSF pressure at the stopcock. Reading can go to an optional
        bedside display. (Different from CoolSpine's saline pressure sensors.)
        */
    }

    part def Display {
        doc /* Optional screen showing CSF pressure from the drain set. */
    }

    part def Stopcock {
        doc /*
        Valve that controls CSF into the burette and is where the pressure
        sensor taps the line.
        */
    }

    part def Burette {
        doc /*
        Clear chamber that receives CSF from the stopcock before it drains
        into the collection bag; used with the scale to read level/pressure.
        */
    }

    part def CollectionBag {
        doc /* Bag that collects CSF from the burette. */
    }

    part def GraduatedScale {
        doc /*
        Ruler / scale next to the burette so staff can read fluid level and
        related pressure values.
        */
    }

    part def LevelingDevice {
        doc /*
        Helps align the scale to a clinical zero height (often near the ear
        canal) so pressure readings are meaningful.
        */
    }

    part def CsfDrain {
        doc /*
        Standard external CSF drain set used beside CoolSpine when ICP /
        drainage monitoring is needed. Fluid path: stopcock → burette → bag,
        with pressure sense, optional display, scale, and leveling.
        Not the CoolSpine saline loop.
        */

        part pressureSensor : PressureSensor;
        part display : Display [0..1];
        part stopcock : Stopcock;
        part burette : Burette;
        part collectionBag : CollectionBag;
        part graduatedScale : GraduatedScale;
        part levelingDevice : LevelingDevice;

        connection csfIntoBurette
            connect stopcock to burette {
            doc /* CSF flows from stopcock into the burette. */
        }
        connection csfToCollectionBag
            connect burette to collectionBag {
            doc /* CSF drains from burette into the bag. */
        }

        connection senseCsfPressure
            connect stopcock to pressureSensor {
            doc /* Pressure is sensed at the stopcock. */
        }

        connection displayCsfPressure
            connect pressureSensor to display {
            doc /* Pressure value shown on the optional display. */
        }

        connection indicateFluidLevel
            connect graduatedScale to burette {
            doc /* Scale is read against the burette fluid level. */
        }

        connection alignScaleLevel
            connect levelingDevice to graduatedScale {
            doc /* Leveling sets the scale to the clinical reference height. */
        }
    }

    // ------------------------------------------------------------------
    // Operating room picture (who is there with the device)
    // ------------------------------------------------------------------

    part def Kontext {
        doc /*
        One operating-room snapshot: CoolSpine device, patient, surgeon,
        anesthesiologist, and optionally a CSF drain.

        CoolSpine's saline stays inside the device loop
        (reservoir → catheter → pump → reservoir). The catheter is the only
        part of that loop inside the patient. The CSF drain is separate
        hospital gear for monitoring, not CoolSpine plumbing.
        */

        part coolSpine : CoolSpineDevice;
        part patient : Patient;
        part surgeon : Surgeon;
        part anesthesiologist : Anesthesiologist;
        part csfDrain : CsfDrain [0..1];

        connection drainPatientCsf
            connect patient to csfDrain {
            doc /* Patient CSF line into the optional drain set. */
        }
    }

    // ------------------------------------------------------------------
    // Who does what during a cooling case (simple sequence)
    // ------------------------------------------------------------------

    part def ClinicalCoolingInteraction {
        doc /*
        Step-by-step clinical flow while CoolSpine is used: surgeon asks for
        cooling, anesthesiologist configures the device, CoolSpine delivers
        therapy, setpoints may change mid-case, then everyone shuts down.
        Same people and device as in the OR context — this is the workflow,
        not a second copy of the hardware.
        */

        ref part surgeon : Surgeon {
            perform operateTherapy.requestCooling;
            perform operateTherapy.requestChange;
            perform operateTherapy.endProcedure;
        }

        ref part anesthesiologist : Anesthesiologist {
            perform operateTherapy.setSetpoints;
            perform operateTherapy.adjustSetpoints;
            perform operateTherapy.stopTherapy;
        }

        ref part coolSpine : CoolSpineDevice {
            perform operateTherapy.deliverTherapy;
            perform operateTherapy.applyAdjustment;
            perform operateTherapy.shutdown;
        }

        perform action operateTherapy {
            doc /*
            Typical order of work:
            1) surgeon requests cooling
            2) anesthesiologist sets flow / temperature
            3) CoolSpine runs
            4) surgeon may ask for a change → anesthesiologist updates → device applies
            5) case ends → stop → device standby
            */

            action requestCooling {
                doc /* Surgeon asks for therapeutic cooling for this patient. */
            }

            action setSetpoints {
                doc /* Anesthesiologist enters initial flow and temperature. */
            }

            action deliverTherapy {
                doc /* CoolSpine runs the saline loop and cools. */
            }

            action requestChange {
                doc /* Surgeon asks for a different setpoint during the case. */
            }

            action adjustSetpoints {
                doc /* Anesthesiologist changes flow / temperature on the UI. */
            }

            action applyAdjustment {
                doc /* CoolSpine applies the new setpoints. */
            }

            action endProcedure {
                doc /* Surgeon says cooling is no longer needed. */
            }

            action stopTherapy {
                doc /* Anesthesiologist stops therapy on the device. */
            }

            action shutdown {
                doc /* CoolSpine stops the loop and goes to standby. */
            }

            first start;
            then requestCooling;
            then setSetpoints;
            then deliverTherapy;
            then requestChange;
            then adjustSetpoints;
            then applyAdjustment;
            then endProcedure;
            then stopTherapy;
            then shutdown;
            then done;
        }
    }
}
