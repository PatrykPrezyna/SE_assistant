// Insulin pump — who is involved. Stakeholders are part definitions,
// the same convention as the spine-cooling context (Patient, Surgeon).
package InsulinPumpContext {

    part def InsulinPump {
        doc /*
        A small wearable pump that delivers insulin under the skin.
        It can run a background (basal) rate and an extra meal (bolus) dose,
        and it stops and alarms if the insulin is not getting through.
        */
    }

    part def Patient {
        doc /*
        The person who wears the pump and lives with diabetes.
        Needs a steady background dose, and an extra dose at meals.
        */
    }

    part def Caregiver {
        doc /*
        A family member or nurse who helps when something goes wrong,
        for example when the pump alarms because the tubing is blocked.
        */
    }

    part def Endocrinologist {
        doc /*
        The clinician who prescribes the basal rate and the carbohydrate
        ratio used to calculate a meal bolus.
        */
    }

    part def Regulator {
        doc /*
        The FDA, or another regulator, who decides whether the pump may
        be sold. Needs evidence that a blocked line stops delivery.
        */
    }

    part def Manufacturer {
        doc /*
        The company that builds the pump. Needs the alarm response to be
        simple enough to explain in the instructions, without special tools.
        */
    }

    part def OperationalContext {
        doc /*
        The pump and the people around it. One pump, worn by one patient,
        with a caregiver, an endocrinologist, a regulator, and a manufacturer
        each having a stake in it.
        */
        part pump : InsulinPump;
        part patient : Patient;
        part caregiver : Caregiver;
        part endocrinologist : Endocrinologist;
        part regulator : Regulator;
        part manufacturer : Manufacturer;
    }
}
