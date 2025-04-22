import React, { useState } from 'react';
import { Settings2, X } from 'lucide-react';
import { Button } from "../components/ui/button";
import { BatterySettings, ElectricitySettings } from '../types';

type AreaCode = 'SE1' | 'SE2' | 'SE3' | 'SE4';

interface CombinedSettingsProps {
  batterySettings: BatterySettings | null;
  electricitySettings: ElectricitySettings | null;
  onBatteryUpdate: (settings: BatterySettings) => void;
  onElectricityUpdate: (settings: ElectricitySettings) => void;
}

export function CombinedSettings({ 
  batterySettings,
  electricitySettings,
  onBatteryUpdate,
  onElectricityUpdate
}: CombinedSettingsProps) {
  // If we don't have settings yet, just show the settings button without functionality
  if (!batterySettings || !electricitySettings) {
    return (
      <Button
        variant="ghost"
        size="icon"
        className="hover:bg-gray-100 rounded-full"
        onClick={() => console.log("Settings not loaded yet")}
      >
        <Settings2 className="h-5 w-5" />
      </Button>
    );
  }

  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<'battery' | 'electricity'>('battery');
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});
  
  // Initialize with the actual settings values once we know they exist
  const [localBatteryValues, setLocalBatteryValues] = useState({
    useActualPrice: batterySettings.useActualPrice,
    totalCapacity: batterySettings.totalCapacity.toString(),
    reservedCapacity: batterySettings.reservedCapacity.toString(),
    estimatedConsumption: "10.0",
    maxChargeDischarge: batterySettings.maxChargeDischarge.toString(),
    chargeCycleCost: batterySettings.chargeCycleCost.toString(),
    chargingPowerRate: batterySettings.chargingPowerRate.toString(),
  });

  const [localElectricityValues, setLocalElectricityValues] = useState({
    markupRate: electricitySettings.markupRate.toString(),
    vatMultiplier: electricitySettings.vatMultiplier.toString(),
    additionalCosts: electricitySettings.additionalCosts.toString(),
    taxReduction: electricitySettings.taxReduction.toString(),
    area: electricitySettings.area
  });

  const validateInput = (field: string, value: number) => {
    const errors: Record<string, string> = {};
    
    // Battery validations
    if (['totalCapacity', 'reservedCapacity', 'estimatedConsumption', 
         'maxChargeDischarge', 'chargeCycleCost', 'chargingPowerRate'].includes(field)) {
      switch (field) {
        case 'totalCapacity':
          if (value < batterySettings.reservedCapacity) {
            errors[field] = `Cannot be less than reserved capacity (${batterySettings.reservedCapacity} kWh)`;
          }
          break;
        case 'reservedCapacity':
          if (value > batterySettings.totalCapacity) {
            errors[field] = `Cannot exceed total capacity (${batterySettings.totalCapacity} kWh)`;
          }
          break;
        case 'estimatedConsumption':
          if (value < 0 || value > 15) {
            errors[field] = 'Must be between 0 and 15 kWh';
          }
          break;
        case 'chargingPowerRate':
          if (value < 0 || value > 100) {
            errors[field] = 'Must be between 0 and 100';
          }
          break;
        default:
          if (value < 0) {
            errors[field] = 'Must be greater than 0';
          }
      }
    }
    
    // Electricity validations
    if (['markupRate', 'additionalCosts', 'taxReduction'].includes(field)) {
      if (value < 0) {
        errors[field] = 'Must be greater than or equal to 0';
      }
    }
    
    if (field === 'vatMultiplier' && value < 1) {
      errors[field] = 'Must be greater than or equal to 1';
    }
    
    setValidationErrors(prev => ({ ...prev, ...errors }));
    return Object.keys(errors).length === 0;
  };

  const handleInputChange = (
    e: React.ChangeEvent<HTMLInputElement>, 
    field: string, 
    setLocalValues: React.Dispatch<React.SetStateAction<any>>
  ) => {
    const newValue = e.target.value.replace(',', '.');
    setLocalValues((prev: any) => ({ ...prev, [field]: newValue }));
    setValidationErrors(prev => ({ ...prev, [field]: '' }));
  };

  const handleInputBlur = (
    field: string, 
    localValues: any,
    settings: any,
    onUpdate: (settings: any) => void,
    setLocalValues: React.Dispatch<React.SetStateAction<any>>
  ) => {
    const value = localValues[field];
    const parsed = parseFloat(value.replace(',', '.'));
    
    if (isNaN(parsed)) {
      setValidationErrors(prev => ({ 
        ...prev, 
        [field]: 'Please enter a valid number' 
      }));
      return;
    }

    if (!validateInput(field, parsed)) {
      return;
    }

    setLocalValues((prev: any) => ({
      ...prev,
      [field]: parsed.toString()
    }));
    
    onUpdate({
      ...settings,
      [field]: parsed
    });
  };

  const handleAreaChange = (area: AreaCode) => {
    setLocalElectricityValues(prev => ({ ...prev, area }));
    onElectricityUpdate({
      ...electricitySettings,
      area
    });
  };

  const handleSwitchChange = (checked: boolean) => {
    onBatteryUpdate({
      ...batterySettings,
      useActualPrice: checked
    });
  };

  // Simple Input component that doesn't rely on your UI library
  const SimpleInput = ({ 
    value, 
    onChange, 
    onBlur, 
    disabled = false 
  }: { 
    value: string, 
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => void, 
    onBlur: () => void, 
    disabled?: boolean 
  }) => (
    <input 
      type="text" 
      value={value} 
      onChange={onChange} 
      onBlur={onBlur}
      disabled={disabled}
      className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100 disabled:text-gray-500"
    />
  );

  // Simple Label component
  const SimpleLabel = ({ children }: { children: React.ReactNode }) => (
    <label className="block text-sm font-medium text-gray-700">{children}</label>
  );

  // Simple Switch component
  const SimpleSwitch = ({ checked, onChange }: { checked: boolean, onChange: (checked: boolean) => void }) => (
    <div 
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${checked ? 'bg-blue-600' : 'bg-gray-200'}`}
      onClick={() => onChange(!checked)}
    >
      <span 
        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'}`} 
      />
    </div>
  );

  try {
    return (
      <>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setIsOpen(true)}
          className="hover:bg-gray-100 rounded-full"
        >
          <Settings2 className="h-5 w-5" />
        </Button>

        {isOpen && (
          <div className="fixed inset-0 z-50 bg-black/50">
            <div className="fixed inset-y-0 left-0 w-96 bg-white shadow-lg p-6 animate-in slide-in-from-left">
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-xl font-semibold">Settings</h2>
                <Button variant="ghost" size="icon" onClick={() => setIsOpen(false)}>
                  <X className="h-5 w-5" />
                </Button>
              </div>

              {/* Simple tabs */}
              <div className="mb-6">
                <div className="flex border-b border-gray-200">
                  <button
                    className={`py-2 px-4 text-center ${activeTab === 'battery' ? 'border-b-2 border-blue-500 font-medium text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
                    onClick={() => setActiveTab('battery')}
                  >
                    Battery
                  </button>
                  <button
                    className={`py-2 px-4 text-center ${activeTab === 'electricity' ? 'border-b-2 border-blue-500 font-medium text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
                    onClick={() => setActiveTab('electricity')}
                  >
                    Electricity
                  </button>
                </div>
              </div>

              {/* Battery Tab Content */}
              {activeTab === 'battery' && (
                <div className="space-y-4">
                  <div className="space-y-2">
                    <SimpleLabel>Total Capacity (kWh)</SimpleLabel>
                    <SimpleInput
                      value={localBatteryValues.totalCapacity}
                      onChange={(e) => handleInputChange(e, 'totalCapacity', setLocalBatteryValues)}
                      onBlur={() => handleInputBlur('totalCapacity', localBatteryValues, batterySettings, onBatteryUpdate, setLocalBatteryValues)}
                    />
                    {validationErrors.totalCapacity && (
                      <span className="text-sm text-red-500">{validationErrors.totalCapacity}</span>
                    )}
                  </div>

                  <div className="space-y-2">
                    <SimpleLabel>Reserved Capacity (kWh)</SimpleLabel>
                    <SimpleInput
                      value={localBatteryValues.reservedCapacity}
                      onChange={(e) => handleInputChange(e, 'reservedCapacity', setLocalBatteryValues)}
                      onBlur={() => handleInputBlur('reservedCapacity', localBatteryValues, batterySettings, onBatteryUpdate, setLocalBatteryValues)}
                    />
                    {validationErrors.reservedCapacity && (
                      <span className="text-sm text-red-500">{validationErrors.reservedCapacity}</span>
                    )}
                  </div>

                  <div className="space-y-2">
                    <SimpleLabel>Estimated Consumption (kWh)</SimpleLabel>
                    <SimpleInput
                      value={localBatteryValues.estimatedConsumption}
                      onChange={(e) => handleInputChange(e, 'estimatedConsumption', setLocalBatteryValues)}
                      onBlur={() => handleInputBlur('estimatedConsumption', localBatteryValues, batterySettings, onBatteryUpdate, setLocalBatteryValues)}
                    />
                    {validationErrors.estimatedConsumption && (
                      <span className="text-sm text-red-500">{validationErrors.estimatedConsumption}</span>
                    )}
                  </div>

                  <div className="space-y-2">
                    <SimpleLabel>Max Charge/Discharge (kW)</SimpleLabel>
                    <SimpleInput
                      value={localBatteryValues.maxChargeDischarge}
                      onChange={(e) => handleInputChange(e, 'maxChargeDischarge', setLocalBatteryValues)}
                      onBlur={() => handleInputBlur('maxChargeDischarge', localBatteryValues, batterySettings, onBatteryUpdate, setLocalBatteryValues)}
                    />
                    {validationErrors.maxChargeDischarge && (
                      <span className="text-sm text-red-500">{validationErrors.maxChargeDischarge}</span>
                    )}
                  </div>

                  <div className="space-y-2">
                    <SimpleLabel>Charge Cycle Cost (SEK)</SimpleLabel>
                    <SimpleInput
                      value={localBatteryValues.chargeCycleCost}
                      onChange={(e) => handleInputChange(e, 'chargeCycleCost', setLocalBatteryValues)}
                      onBlur={() => handleInputBlur('chargeCycleCost', localBatteryValues, batterySettings, onBatteryUpdate, setLocalBatteryValues)}
                    />
                    {validationErrors.chargeCycleCost && (
                      <span className="text-sm text-red-500">{validationErrors.chargeCycleCost}</span>
                    )}
                  </div>

                  <div className="space-y-2">
                    <SimpleLabel>Charging Power Rate (%)</SimpleLabel>
                    <SimpleInput
                      value={localBatteryValues.chargingPowerRate}
                      onChange={(e) => handleInputChange(e, 'chargingPowerRate', setLocalBatteryValues)}
                      onBlur={() => handleInputBlur('chargingPowerRate', localBatteryValues, batterySettings, onBatteryUpdate, setLocalBatteryValues)}
                    />
                    {validationErrors.chargingPowerRate && (
                      <span className="text-sm text-red-500">{validationErrors.chargingPowerRate}</span>
                    )}
                  </div>
                </div>
              )}

              {/* Electricity Tab Content */}
              {activeTab === 'electricity' && (
                <div className="space-y-4">
                  <div className="flex items-center space-x-2 py-2">
                    <SimpleSwitch
                      checked={batterySettings.useActualPrice}
                      onChange={handleSwitchChange}
                    />
                    <SimpleLabel>Use Actual Electricity Price</SimpleLabel>
                  </div>

                  <div className="space-y-2">
                    <SimpleLabel>Area</SimpleLabel>
                    <select
                      value={localElectricityValues.area}
                      onChange={(e) => handleAreaChange(e.target.value as AreaCode)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    >
                      {['SE1', 'SE2', 'SE3', 'SE4'].map((area) => (
                        <option key={area} value={area}>{area}</option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-2">
                    <SimpleLabel>Markup Rate (SEK/kWh)</SimpleLabel>
                    <SimpleInput
                      value={localElectricityValues.markupRate}
                      onChange={(e) => handleInputChange(e, 'markupRate', setLocalElectricityValues)}
                      onBlur={() => handleInputBlur('markupRate', localElectricityValues, electricitySettings, onElectricityUpdate, setLocalElectricityValues)}
                      disabled={!batterySettings.useActualPrice}
                    />
                    {validationErrors.markupRate && (
                      <span className="text-sm text-red-500">{validationErrors.markupRate}</span>
                    )}
                  </div>

                  <div className="space-y-2">
                    <SimpleLabel>VAT Multiplier</SimpleLabel>
                    <SimpleInput
                      value={localElectricityValues.vatMultiplier}
                      onChange={(e) => handleInputChange(e, 'vatMultiplier', setLocalElectricityValues)}
                      onBlur={() => handleInputBlur('vatMultiplier', localElectricityValues, electricitySettings, onElectricityUpdate, setLocalElectricityValues)}
                      disabled={!batterySettings.useActualPrice}
                    />
                    {validationErrors.vatMultiplier && (
                      <span className="text-sm text-red-500">{validationErrors.vatMultiplier}</span>
                    )}
                  </div>

                  <div className="space-y-2">
                    <SimpleLabel>Additional Costs (SEK/kWh)</SimpleLabel>
                    <SimpleInput
                      value={localElectricityValues.additionalCosts}
                      onChange={(e) => handleInputChange(e, 'additionalCosts', setLocalElectricityValues)}
                      onBlur={() => handleInputBlur('additionalCosts', localElectricityValues, electricitySettings, onElectricityUpdate, setLocalElectricityValues)}
                      disabled={!batterySettings.useActualPrice}
                    />
                    {validationErrors.additionalCosts && (
                      <span className="text-sm text-red-500">{validationErrors.additionalCosts}</span>
                    )}
                  </div>

                  <div className="space-y-2">
                    <SimpleLabel>Tax Reduction (SEK/kWh)</SimpleLabel>
                    <SimpleInput
                      value={localElectricityValues.taxReduction}
                      onChange={(e) => handleInputChange(e, 'taxReduction', setLocalElectricityValues)}
                      onBlur={() => handleInputBlur('taxReduction', localElectricityValues, electricitySettings, onElectricityUpdate, setLocalElectricityValues)}
                      disabled={!batterySettings.useActualPrice}
                    />
                    {validationErrors.taxReduction && (
                      <span className="text-sm text-red-500">{validationErrors.taxReduction}</span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </>
    );
  } catch (error) {
    console.error("Error in CombinedSettings component:", error);
    return (
      <Button
        variant="ghost"
        size="icon"
        onClick={() => alert("Settings component error, please reload the page")}
        className="hover:bg-gray-100 rounded-full"
      >
        <Settings2 className="h-5 w-5" />
      </Button>
    );
  }
}