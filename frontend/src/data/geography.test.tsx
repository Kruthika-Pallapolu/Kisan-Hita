import { describe, expect, it, vi } from 'vitest';
import { indianGeography, supportedGeographyLanguages, stateByCanonicalName, districtByCanonicalName, districtsForState, districtsForStateCode, geographicDisplayName } from './geography';
import { GeographicSelector } from '../app/App';
import { fireEvent, render, screen } from '@testing-library/react';
import geographySnapshot from './india-geography.json';
import { translate } from '../localization';

describe('bundled Indian geography', () => {
  it('contains all 28 states and 8 union territories with 790 unique LGD district codes', () => {
    expect(geographySnapshot.source).toContain('Local Government Directory');
    expect(geographySnapshot.retrievedOn).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(geographySnapshot.languages).toEqual(supportedGeographyLanguages);
    expect(indianGeography.filter((item) => item.type === 'state')).toHaveLength(28);
    expect(indianGeography.filter((item) => item.type === 'union_territory')).toHaveLength(8);
    const districts = indianGeography.flatMap((item) => item.districts);
    expect(districts).toHaveLength(790);
    expect(new Set(districts.map((item) => item.lgdCode)).size).toBe(790);
    expect(indianGeography.every((item) => item.lgdCode && item.name)).toBe(true);
    expect(new Set(indianGeography.map((item) => item.lgdCode)).size).toBe(36);
    expect(districts.every((item) => item.stateCode && item.name)).toBe(true);
  });

  it('links each district to its containing state and provides every language label or recorded fallback', () => {
    for (const state of indianGeography) {
      for (const language of supportedGeographyLanguages) expect(state.names[language] || state.fallbackLanguages.includes(language)).toBeTruthy();
      for (const district of state.districts) {
        expect(district.stateCode).toBe(state.lgdCode);
        for (const language of supportedGeographyLanguages) {
          expect(Boolean(district.names[language]) || district.fallbackLanguages.includes(language)).toBe(true);
          expect(district.names[language]).toBeTruthy();
        }
      }
    }
  });

  it('filters to the selected state, clears district on state change, and updates labels by language', () => {
    expect(districtsForState('Telangana').some((item) => item.name === 'Warangal')).toBe(true);
    expect(districtsForState('Maharashtra').some((item) => item.name === 'Warangal')).toBe(false);
    expect(districtByCanonicalName('Telangana', 'Warangal')?.stateCode).toBe(stateByCanonicalName('Telangana')?.lgdCode);
    expect(geographicDisplayName(districtByCanonicalName('Telangana', 'Warangal')!, 'te')).toBe('వరంగల్');
    const onStateChange = vi.fn();
    const onDistrictChange = vi.fn();
    const { rerender } = render(<GeographicSelector idPrefix="test" language="en" state="Telangana" district="Warangal" onStateChange={onStateChange} onDistrictChange={onDistrictChange} />);
    const district = screen.getByLabelText('Your district or town') as HTMLSelectElement;
    expect([...district.options].some((option) => option.value === 'Pune')).toBe(false);
    fireEvent.change(screen.getByLabelText('Your state'), { target: { value: 'Maharashtra' } });
    expect(onStateChange).toHaveBeenCalledWith('Maharashtra');
    expect(onDistrictChange).toHaveBeenCalledWith('');
    rerender(<GeographicSelector idPrefix="test" language="te" state="Telangana" district="Warangal" onStateChange={onStateChange} onDistrictChange={onDistrictChange} />);
    expect(screen.getByLabelText('మీ జిల్లా లేదా పట్టణం')).toHaveDisplayValue('వరంగల్');
  });

  it('filters actual bundled districts by LGD parent-state code for the requested regions', () => {
    const examples = [
      { state: 'Karnataka', included: ['Bengaluru Urban', 'Belagavi', 'Mysuru'], excluded: ['Warangal', 'Pune'], excludedFragment: 'Nellore' },
      { state: 'Andhra Pradesh', included: ['Guntur', 'Kurnool'], excluded: ['Pune'], includedFragment: 'Nellore' },
      { state: 'Telangana', included: ['Warangal', 'Nizamabad', 'Karimnagar'], excluded: [] },
      { state: 'Maharashtra', included: ['Pune', 'Mumbai', 'Nagpur'], excluded: [], excludedFragment: 'Nellore' },
      { state: 'Tamil Nadu', included: ['Coimbatore', 'Chennai', 'Madurai'], excluded: [] },
      { state: 'Kerala', included: ['Palakkad', 'Ernakulam'], excluded: [] },
    ];
    const all = indianGeography.flatMap((state) => state.districts);
    for (const example of examples) {
      const parent = stateByCanonicalName(example.state)!;
      const districts = districtsForStateCode(parent.lgdCode);
      expect(districts.length).toBeGreaterThan(0);
      expect(districts.every((district) => district.stateCode === parent.lgdCode)).toBe(true);
      expect(districts.map((district) => district.lgdCode)).toEqual(all.filter((district) => district.stateCode === parent.lgdCode).map((district) => district.lgdCode));
      for (const name of example.included) expect(districts.some((district) => district.name === name)).toBe(true);
      if (example.includedFragment) expect(districts.some((district) => district.name.includes(example.includedFragment!))).toBe(true);
      for (const name of example.excluded) expect(districts.some((district) => district.name === name)).toBe(false);
      if (example.excludedFragment) expect(districts.some((district) => district.name.includes(example.excludedFragment!))).toBe(false);
    }
  });

  it('uses the full dataset in each shared selector and never carries a previous state district', () => {
    for (const idPrefix of ['market', 'farm', 'crop']) {
      let selectedState = 'Karnataka';
      let selectedDistrict = 'Mysuru';
      const view = render(<GeographicSelector idPrefix={idPrefix} language="en" state={selectedState} district={selectedDistrict}
        onStateChange={(value) => { selectedState = value; selectedDistrict = ''; }} onDistrictChange={(value) => { selectedDistrict = value; }} />);
      const districtSelect = view.container.querySelector(`#${idPrefix}-district`) as HTMLSelectElement;
      expect([...districtSelect.options].some((option) => option.value.includes('Nellore') || option.value === 'Warangal' || option.value === 'Pune')).toBe(false);
      view.rerender(<GeographicSelector idPrefix={idPrefix} language="en" state="Andhra Pradesh" district="" onStateChange={() => {}} onDistrictChange={() => {}} />);
      const andhra = view.container.querySelector(`#${idPrefix}-district`) as HTMLSelectElement;
      expect([...andhra.options].some((option) => option.value === 'Sri Potti Sriramulu Nellore')).toBe(true);
      expect([...andhra.options].some((option) => option.value === 'Pune')).toBe(false);
      view.rerender(<GeographicSelector idPrefix={idPrefix} language="en" state="Maharashtra" district="" onStateChange={() => {}} onDistrictChange={() => {}} />);
      const maharashtra = view.container.querySelector(`#${idPrefix}-district`) as HTMLSelectElement;
      expect([...maharashtra.options].some((option) => option.value === 'Pune')).toBe(true);
      expect([...maharashtra.options].some((option) => option.value === 'Sri Potti Sriramulu Nellore')).toBe(false);
      view.unmount();
    }
  });

  it('renders the state-then-district flow in all seven languages while keeping canonical values', () => {
    for (const language of supportedGeographyLanguages) {
      const onStateChange = vi.fn();
      const onDistrictChange = vi.fn();
      expect(translate(language, 'useLocation')).toBeTruthy();
      expect(translate(language, 'noDistrictsAvailable')).toBeTruthy();
      if (language !== 'en') expect(translate(language, 'useLocation')).not.toBe(translate('en', 'useLocation'));
      const view = render(<GeographicSelector idPrefix={`geo-${language}`} language={language}
        state="" district="" onStateChange={onStateChange} onDistrictChange={onDistrictChange} />);
      const stateSelect = view.container.querySelector(`#geo-${language}-state`) as HTMLSelectElement;
      const districtSelect = view.container.querySelector(`#geo-${language}-district`) as HTMLSelectElement;
      expect(districtSelect.disabled).toBe(true);
      expect(stateSelect.options[0].text).toBe(translate(language, 'chooseState'));
      expect(districtSelect.options[0].text).toBe(translate(language, 'selectStateFirst'));
      fireEvent.change(stateSelect, { target: { value: 'Telangana' } });
      expect(onStateChange).toHaveBeenCalledWith('Telangana');
      expect(onDistrictChange).toHaveBeenCalledWith('');
      view.rerender(<GeographicSelector idPrefix={`geo-${language}`} language={language}
        state="Telangana" district="" onStateChange={onStateChange} onDistrictChange={onDistrictChange} />);
      const districtAfterState = view.container.querySelector(`#geo-${language}-district`) as HTMLSelectElement;
      expect(districtAfterState.disabled).toBe(false);
      expect(districtAfterState.options[0].text).toBe(translate(language, 'chooseDistrict'));
      fireEvent.change(districtAfterState, { target: { value: 'Warangal' } });
      expect(onDistrictChange).toHaveBeenCalledWith('Warangal');
      view.rerender(<GeographicSelector idPrefix={`geo-${language}`} language={language}
        state="Telangana" district="Warangal" onStateChange={onStateChange} onDistrictChange={onDistrictChange} />);
      expect(view.container.querySelector(`#geo-${language}-district`)).toHaveDisplayValue(geographicDisplayName(districtByCanonicalName('Telangana', 'Warangal')!, language));
      view.unmount();
    }
  });
});
