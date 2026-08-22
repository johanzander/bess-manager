import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { PricingFormSection } from '../PricingFormSection';
import type { PricingForm } from '../PricingFormSection';

const BASE_FORM: PricingForm = {
  currency: 'SEK',
  provider: 'nordpool_official',
  nordpoolConfigEntryId: '',
  nordpoolEntity: '',
  octopusImportTodayEntity: '',
  octopusImportTomorrowEntity: '',
  octopusExportTodayEntity: '',
  octopusExportTomorrowEntity: '',
  entsoeEntity: '',
  area: '',
  markupRate: 0,
  vatMultiplier: 1.25,
  additionalCosts: 0,
  taxReduction: 0,
  spotMultiplier: 1.0,
  exportSpotMultiplier: 1.0,
};

describe('PricingFormSection', () => {
  it('allows a negative Export Compensation value (nätnytta can be a cost, not just a credit)', () => {
    const onChange = vi.fn();
    render(<PricingFormSection form={BASE_FORM} onChange={onChange} />);

    const input = screen.getByLabelText(/Export Compensation/i);
    expect(input).not.toHaveAttribute('min', '0');

    fireEvent.change(input, { target: { value: '-0.05' } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ taxReduction: -0.05 }));
  });

  it('reflects a negative Export Compensation in the sell price preview', () => {
    render(<PricingFormSection form={{ ...BASE_FORM, taxReduction: -0.05 }} onChange={vi.fn()} />);

    expect(screen.getByText('0.95 SEK/kWh')).toBeInTheDocument();
  });
});
