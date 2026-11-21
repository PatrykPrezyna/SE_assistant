// Generated from process/stakeholders.yaml by stakeholder_analysis.py. Edit the register and run the tool again. Hand edits are overwritten.
package Stakeholders {
    abstract part def Stakeholder {
        doc /* A role with a stake in the system of interest. */
    }

    abstract part def Customer :> Stakeholder {
        doc /* A person or organization who uses the product or is directly affected by it. */
    }

    abstract part def InternalStakeholder :> Stakeholder {
        doc /* A role inside the team that develops the product. */
    }

    abstract part def RegulatoryStakeholder :> Stakeholder {
        doc /* A body that decides whether the product may be placed on the market. */
    }

    part def Surgeon :> Customer {
        doc /* Uses the device on a patient during the procedure. Category: Customer. */
    }

    part def SystemsEngineer :> InternalStakeholder {
        doc /* Develops the product and keeps the model consistent with the design. Category: Internal stakeholder. */
    }

    part def NotifiedBody :> RegulatoryStakeholder {
        doc /* Reviews the technical documentation before the device is placed on the market. Category: Regulatory. */
    }

    part def InfusionPump {
        doc /* System of interest named in the stakeholder register. Later activities add its structure. */
    }

    part def OperationalContext {
        doc /* The system of interest and the stakeholders around it. */
        part infusionPump : InfusionPump;
        part surgeon : Surgeon;
        part systemsEngineer : SystemsEngineer;
        part notifiedBody : NotifiedBody;
    }
}
