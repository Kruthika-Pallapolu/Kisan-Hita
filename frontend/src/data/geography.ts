import rawGeography from './india-geography.json';
import type { Locale } from '../localization';

export type GeographicNames = Record<Locale, string>;
export type DistrictRecord = { lgdCode: string; stateCode: string; name: string; names: GeographicNames; fallbackLanguages: Locale[] };
export type StateRecord = { lgdCode: string; name: string; type: 'state' | 'union_territory'; names: GeographicNames; fallbackLanguages: Locale[]; districts: DistrictRecord[] };
export const supportedGeographyLanguages: Locale[] = ['en', 'te', 'hi', 'ta', 'kn', 'ml', 'mr'];
export const indianGeography = (rawGeography as { states: StateRecord[] }).states
  .map((state) => ({ ...state, districts: [...state.districts].sort((a,b) => a.name.localeCompare(b.name)) }))
  .sort((a,b) => a.name.localeCompare(b.name));
const allDistricts = indianGeography.flatMap((state) => state.districts);

export function stateByCanonicalName(name: string | undefined): StateRecord | undefined {
  const normalized = (name ?? '').trim().toLocaleLowerCase('en');
  return indianGeography.find((state) => state.name.toLocaleLowerCase('en') === normalized);
}

export function districtByCanonicalName(stateName: string | undefined, districtName: string | undefined): DistrictRecord | undefined {
  const state = stateByCanonicalName(stateName);
  const normalized = (districtName ?? '').trim().toLocaleLowerCase('en');
  return districtsForStateCode(state?.lgdCode).find((district) => district.name.toLocaleLowerCase('en') === normalized);
}

export function districtsForState(stateName: string | undefined): DistrictRecord[] {
  return districtsForStateCode(stateByCanonicalName(stateName)?.lgdCode);
}

/** Filter the bundled district records by their canonical LGD parent-state code. */
export function districtsForStateCode(stateCode: string | undefined): DistrictRecord[] {
  if (!stateCode) return [];
  return allDistricts.filter((district) => district.stateCode === stateCode);
}

export function geographicDisplayName(record: StateRecord | DistrictRecord, language: string): string {
  const locale = language.toLowerCase().split('-')[0] as Locale;
  return record.names[locale] || record.name;
}

