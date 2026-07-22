import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveApiProxyTarget } from '../vite.config.js'

test('verification mode uses the process-injected API origin', () => {
  assert.equal(resolveApiProxyTarget({ VITE_API_BASE: 'http://127.0.0.1:54321' }), 'http://127.0.0.1:54321')
})

test('API proxy retains the development fallback without an override', () => {
  assert.equal(resolveApiProxyTarget({}), 'http://localhost:8000')
})
