const {test} = require('node:test');
const assert = require('node:assert/strict');
const {add} = require('../math.cjs');
test('addition', () => assert.equal(add(3,2), 5));
