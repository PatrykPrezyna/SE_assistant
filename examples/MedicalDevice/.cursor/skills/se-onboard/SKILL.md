---
name: se-onboard
description: >-
  Onboards the user to the CoolSpine Systems Engineering assistant in this
  MedicalDevice example. Use when the user says hello, asks for help getting
  started, wants an overview of the model, or invokes /se-onboard.
---

# SE onboard

## Greeting

Start with exactly:

> Hi, I am your SE assistant — let's build something together.

## Then do this

1. Give a **one-paragraph** overview of CoolSpine (therapeutic temperature control; saline cooling for spinal procedures).
2. Point at the three model files (package name = file stem):
   - `CoolSpineRequirements.sysml` — requirements
   - `CoolSpineSystem.sysml` — device structure
   - `CoolSpineSystemContext.sysml` — patient / clinical context
3. Mention `Spec/` for datasheets and source material.
4. Ask what they want to do next, offering choices such as:
   - Add or refine a requirement
   - Detail a hardware part from a datasheet
   - Improve patient/context interfaces
   - Validate the SysML (`/validate-sysml`)
   - Explore the model in sysml-explorer (if available)

Keep the reply short; do not dump the whole model.
