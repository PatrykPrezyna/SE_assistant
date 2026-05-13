package TherapeuticTemperatureControlSystem {
  
  // Port definitions
  port def ElectricalPower {
    out voltage: Real;
    out current: Real;
  }
  
  port def FluidFlow {
    out temperature: Real [°C];
    out flowRate: Real [ml/min];
  }
  
  port def UserControl {
    in targetTemperature: Real;
    in flowRateSetpoint: Real;
    out systemStatus: String;
  }
  
  port def AmbientInterface {
    in ambientTemperature: Real;
    out wasteHeat: Real;
  }

  // Block definitions
  block PowerSupplyAndBattery {
    port acInput: ElectricalPower;
    port dcOutput: ElectricalPower;
  }

  block UserInterface {
    port power: ElectricalPower;
    port userControl: UserControl;
    port display: UserControl;
  }

  block CustomMicroRefrigerationUnit {
    port power: ElectricalPower;
    port fluidIn: FluidFlow;
    port fluidOut: FluidFlow;
    port ambient: AmbientInterface;
    port coolingRateControl: UserControl;
  }

  block FluidReservoir {
    port warmSalineOut: FluidFlow;
    port coldSalineOut: FluidFlow;
    port refill: FluidFlow;
  }

  block PeristalticPump {
    port power: ElectricalPower;
    port flowRateControl: UserControl;
    port fluidIn: FluidFlow;
    port fluidOut: FluidFlow;
  }

  block Patient {
    port warmSalineIn: FluidFlow;
    port coldSalineIn: FluidFlow;
    port csfDrainOut: FluidFlow;
  }

  // System composition
  part system : System {
    part psu: PowerSupplyAndBattery;
    part ui: UserInterface;
    part microRef: CustomMicroRefrigerationUnit;
    part reservoir: FluidReservoir;
    part pump: PeristalticPump;
    part patient: Patient;

    // Connections
    connect psu.dcOutput to ui.power;
    connect psu.dcOutput to microRef.power;
    connect psu.dcOutput to pump.power;
    
    connect ui.userControl to microRef.coolingRateControl;
    connect ui.userControl to pump.flowRateControl;
    
    connect microRef.fluidOut to reservoir.refill;
    connect reservoir.warmSalineOut to pump.fluidIn;
    connect pump.fluidOut to patient.warmSalineIn;
    
    connect reservoir.coldSalineOut to patient.coldSalineIn;
  }
}