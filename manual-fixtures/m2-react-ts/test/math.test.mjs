import {test} from 'node:test';
import assert from 'node:assert/strict';
import {add} from '../lib/math.js';
test('positive addition', () => assert.equal(add(3, 2), 5));
test('negative addition', () => assert.equal(add(-3, -2), -5));
