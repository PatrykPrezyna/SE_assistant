// Generated from process/stakeholders.yaml by stakeholder_analysis.py. Edit the register and run the tool again. Hand edits are overwritten.
package UserNeeds {
    private import Stakeholders::*;

    requirement def UserNeed {
        doc /* A need stated by one stakeholder, before it is turned into a system requirement. */
    }

    requirement <'NEED-1'> SetTargetTemperature : UserNeed {
        doc /* The surgeon needs to set the target temperature without looking away from the surgical field. Stakeholder: Surgeon (Customer). */
        stakeholder surgeon : Surgeon;
    }

    requirement <'NEED-2'> StableTemperature : UserNeed {
        doc /* The surgeon needs the delivered temperature to stay at the set value for the whole procedure. Stakeholder: Surgeon (Customer). */
        stakeholder surgeon : Surgeon;
    }

    requirement <'NEED-3'> TraceableNeeds : UserNeed {
        doc /* The systems engineer needs every later requirement to trace to a stakeholder need. Stakeholder: SystemsEngineer (Internal stakeholder). */
        stakeholder systemsEngineer : SystemsEngineer;
    }

    requirement <'NEED-4'> ShownConformity : UserNeed {
        doc /* The notified body needs each applicable requirement to have traceable evidence of conformity. Stakeholder: NotifiedBody (Regulatory). */
        stakeholder notifiedBody : NotifiedBody;
    }
}
