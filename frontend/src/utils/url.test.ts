import { describe, it, expect } from 'vitest';
import { buildMapsUrl, numericRouteId } from './url';
import { GOOGLE_MAPS_SEARCH_URL } from '../constants/core';

describe('buildMapsUrl', () => {
  it('prefers coordinates over address', () => {
    expect(buildMapsUrl(59.437, 24.7536, 'Vabaduse väljak')).toBe(`${GOOGLE_MAPS_SEARCH_URL}59.437,24.7536`);
  });

  it('handles equator/meridian coordinates (0,0) instead of falling through to address', () => {
    expect(buildMapsUrl(0, 0, 'Null Island')).toBe(`${GOOGLE_MAPS_SEARCH_URL}0,0`);
  });

  it('falls back to the address when coordinates are missing', () => {
    expect(buildMapsUrl(null, null, 'Vabaduse väljak')).toBe(`${GOOGLE_MAPS_SEARCH_URL}${encodeURIComponent('Vabaduse väljak')}`);
  });

  it('returns null when neither coordinates nor address are available', () => {
    expect(buildMapsUrl(null, null, null)).toBeNull();
  });
});

describe('numericRouteId', () => {
  it('accepts plain digits only', () => {
    expect(numericRouteId('42')).toBe('42');
    expect(numericRouteId('..')).toBeUndefined();
    expect(numericRouteId('1/../2')).toBeUndefined();
    expect(numericRouteId('7?x')).toBeUndefined();
    expect(numericRouteId('')).toBeUndefined();
    expect(numericRouteId(undefined)).toBeUndefined();
  });
});
