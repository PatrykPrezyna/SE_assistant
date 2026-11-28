// User needs: what each stakeholder asks for, in their words.
// A need is a requirement definition that specializes UserNeed.
package InsulinPumpNeeds {

    requirement def UserNeed {
        doc /*
        A need stated by a stakeholder, before it is turned into a
        requirement on the pump itself.
        */
    }

    requirement def <'NEED-1'> SteadyBasal :> UserNeed {
        doc /*
        The patient needs a steady background dose of insulin through
        the day and the night.
        */
    }

    requirement def <'NEED-2'> MealBolus :> UserNeed {
        doc /*
        The patient needs an extra dose at a meal, based on the
        carbohydrates they are about to eat.
        */
    }

    requirement def <'NEED-3'> PrescribedRatio :> UserNeed {
        doc /*
        The endocrinologist needs that meal dose to follow the
        carbohydrate ratio they prescribed.
        */
    }

    requirement def <'NEED-4'> OcclusionAlarm :> UserNeed {
        doc /*
        The caregiver needs a clear alarm when insulin is not getting
        through, and a simple choice about what to do next.
        */
    }

    requirement def <'NEED-5'> MarketEvidence :> UserNeed {
        doc /*
        The regulator (FDA) needs evidence that a blocked line stops
        delivery and raises an alarm.
        */
    }

    requirement def <'NEED-6'> SimpleReset :> UserNeed {
        doc /*
        The manufacturer needs the caregiver to be able to clear a
        blockage and restart the pump without special tools.
        */
    }
}
