import {expect,it} from 'vitest';
import {normalizeName} from '../src/settings';
it('normalizes ordinary display names',()=>{expect(normalizeName('  M5 verified A  ')).toBe('M5 verified A');});
it('bounds storage input',()=>{expect(normalizeName('x'.repeat(121))).toHaveLength(120);});
