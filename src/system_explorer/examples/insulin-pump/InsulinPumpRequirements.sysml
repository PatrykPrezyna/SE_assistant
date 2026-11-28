// System requirements derived from the user needs.
// The explorer draws «satisfy». A requirement that comes from a need
// satisfies that need, which is the trace this tool can show.
package InsulinPumpRequirements {
    private import InsulinPumpNeeds::*;

    requirement def SystemRequirement {
        doc /*
        A requirement on the pump, derived from one or more user needs.
        */
    }

    requirement def <'REQ-1'> DeliverBasalRate :> SystemRequirement {
        doc /*
        Derived from NEED-1 (Steady basal).
        The pump shall deliver the programmed basal rate, and the amount
        delivered over an hour shall stay within 5 percent of that rate.
        */
        satisfy 'NEED-1';
    }

    requirement def <'REQ-2'> ConfirmedBolus :> SystemRequirement {
        doc /*
        Derived from NEED-2 (Meal bolus) and NEED-3 (Prescribed ratio).
        The pump shall compute a bolus from the carbohydrates entered and
        the prescribed ratio, and shall deliver it only after the patient
        confirms the dose.
        */
        satisfy 'NEED-2';
        satisfy 'NEED-3';
    }

    requirement def <'REQ-3'> StopOnOcclusion :> SystemRequirement {
        doc /*
        Derived from NEED-4 (Occlusion alarm), NEED-5 (Market evidence),
        and NEED-6 (Simple reset).
        The pump shall stop delivery and raise an alarm when the line is
        blocked, and shall allow delivery to resume after the line is cleared.
        */
        satisfy 'NEED-4';
        satisfy 'NEED-5';
        satisfy 'NEED-6';
    }
}
