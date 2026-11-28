// What people do with the pump. Actors are usages of the part definitions
// in the context file. Only Handle Occlusion Alarm has an activity.
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
        subject pump : InsulinPump {
            perform handleOcclusion.raiseAlarm;
            perform handleOcclusion.resumeBasal;
            perform handleOcclusion.holdDelivery;
        }
        actor patient : Patient {
            perform handleOcclusion.noticeAlarm;
        }
        actor caregiver : Caregiver {
            perform handleOcclusion.checkLine;
            perform handleOcclusion.clearLine;
            perform handleOcclusion.callForHelp;
        }
        satisfy 'REQ-3';

        perform action handleOcclusion {
            action raiseAlarm {
                doc /* The pump sounds the occlusion alarm and stops the motor. */
            }
            action noticeAlarm {
                doc /* The patient hears the alarm. */
            }
            action checkLine {
                doc /* The caregiver looks at the tubing and the infusion set. */
            }
            action clearLine {
                doc /* The caregiver straightens the tubing or replaces the set. */
            }
            then resumeBasal;
            action resumeBasal {
                doc /* The pump starts the programmed basal rate again. */
            }
            then done;
            action holdDelivery {
                doc /* The pump keeps delivery stopped. */
            }
            then callForHelp;
            action callForHelp {
                doc /* The caregiver calls the clinic or the endocrinologist. */
            }
            then done;

            first start;
            then raiseAlarm;
            then noticeAlarm;
            then checkLine;
            then decide;
              if clear then clearLine;
              else holdDelivery;
        }
    }
}
