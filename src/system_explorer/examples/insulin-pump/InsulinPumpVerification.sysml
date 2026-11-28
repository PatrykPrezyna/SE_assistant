// One check that the basal requirement is actually met.
// «verify» is drawn from this verification case to REQ-1.
package InsulinPumpVerification {
    private import InsulinPumpContext::*;
    private import InsulinPumpRequirements::*;

    verification def <'VER-1'> BasalRateBenchTest {
        doc /*
        Bench test of the basal rate. Run the programmed rate and weigh
        the insulin that came out. Passes when the delivered amount stays
        within 5 percent of the rate.
        */
        subject pump : InsulinPump;
        objective {
            doc /* Pass when the weighed dose is within 5 percent of REQ-1. */
            verify requirement 'REQ-1';
        }
    }
}
