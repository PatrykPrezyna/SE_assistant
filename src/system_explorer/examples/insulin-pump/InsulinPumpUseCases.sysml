// What people do with the pump. Actors are usages of the part definitions
// in the context file. Only Handle Occlusion Alarm has a process.
// The steps are standard SysML v2: the use case owns the actions,
// each actor's body says which steps that person performs, and
// first/then, decide/if/else, and merge give the order. This is the
// spelling the swimlane view reads (see the activity-diagram work).
package InsulinPumpUseCases {
    private import InsulinPumpContext::*;
    private import InsulinPumpRequirements::*;

    use case def DeliverBasalInsulin {
        doc /*
        Deliver the background dose. The pump runs the programmed basal
        rate on its own while the patient wears it.
        */
        subject pump : InsulinPump;
        actor patient : Patient;
        satisfy 'REQ-1';
    }

    use case def DeliverBolus {
        doc /*
        Deliver a meal dose. The patient enters the carbohydrates. The pump
        uses the ratio the endocrinologist prescribed, shows the dose, and
        delivers it after the patient confirms.
        */
        subject pump : InsulinPump;
        actor patient : Patient;
        actor endocrinologist : Endocrinologist;
        satisfy 'REQ-2';
    }

    use case def HandleOcclusionAlarm {
        doc /*
        Handle a blocked line. The pump stops and alarms. The patient
        notices. The caregiver checks the line and either clears it or
        calls for help with delivery still stopped.
        */
        actor pump : InsulinPump {
            perform 'Raise Alarm';
            perform 'Resume Basal';
            perform 'Hold Delivery';
        }
        actor patient : Patient {
            perform 'Notice Alarm';
        }
        actor caregiver : Caregiver {
            perform 'Check Line';
            perform 'Clear Line';
            perform 'Call For Help';
        }
        satisfy 'REQ-3';

        action 'Raise Alarm' {
            doc /* The pump sounds the occlusion alarm and stops the motor. */
        }
        action 'Notice Alarm' {
            doc /* The patient hears the alarm. */
        }
        action 'Check Line' {
            doc /* The caregiver looks at the tubing and the infusion set. */
        }
        action 'Clear Line' {
            doc /* The caregiver straightens the tubing or replaces the set. */
        }
        action 'Resume Basal' {
            doc /* The pump starts the programmed basal rate again. */
        }
        action 'Hold Delivery' {
            doc /* The pump keeps delivery stopped. */
        }
        action 'Call For Help' {
            doc /* The caregiver calls the clinic or the endocrinologist. */
        }

        attribute clear : Boolean;
        decide decide1;
        merge merge1;

        first start then 'Raise Alarm';
        first 'Raise Alarm' then 'Notice Alarm';
        first 'Notice Alarm' then 'Check Line';
        first 'Check Line' then decide1;
        if clear then 'Clear Line';
        else 'Hold Delivery';
        first 'Clear Line' then 'Resume Basal';
        first 'Resume Basal' then merge1;
        first 'Hold Delivery' then 'Call For Help';
        first 'Call For Help' then merge1;
        first merge1 then done;
    }
}
