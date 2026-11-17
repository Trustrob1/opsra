import test from 'node:test'
import assert from 'node:assert/strict'
import { validateDetails, validateCode, creditLine, planLine, naira } from './chatSignupLogic.js'

const GOOD = { business_name: 'Glow Salon', full_name: 'Ada Obi', email: 'ada@glow.example', phone: '0803 123 4567', accept_terms: true }

test('good details pass', () => {
  assert.equal(validateDetails(GOOD), '')
})

test('each missing detail gives its own plain message, in the order they appear on the form', () => {
  assert.equal(validateDetails({ ...GOOD, business_name: 'x' }), 'Please enter your business name.')
  assert.equal(validateDetails({ ...GOOD, full_name: ' ' }), 'Please enter your name.')
  assert.equal(validateDetails({ ...GOOD, email: 'nope' }), 'Please enter a valid email address.')
  assert.equal(validateDetails({ ...GOOD, phone: '12345' }), 'Enter your WhatsApp number, for example 0803 123 4567.')
  assert.equal(validateDetails({ ...GOOD, phone: '1'.repeat(16) }), 'Enter your WhatsApp number, for example 0803 123 4567.')
  assert.equal(validateDetails({ ...GOOD, accept_terms: false }), 'Please accept the terms to continue.')
  assert.equal(validateDetails(), 'Please enter your business name.')
})

test('a phone number may be typed with spaces, plus and dashes', () => {
  assert.equal(validateDetails({ ...GOOD, phone: '+234 803-123-4567' }), '')
})

test('code and password are checked', () => {
  assert.equal(validateCode('123456', 'longenough'), '')
  assert.equal(validateCode('123 456', 'longenough'), '')
  assert.equal(validateCode('12345', 'longenough'), 'Enter the 6-digit code from your email.')
  assert.equal(validateCode('123456', 'short'), 'Choose a password of at least 8 characters.')
})

test('the free credit line comes from the setting', () => {
  assert.equal(creditLine({ starter_credit_ngn: 2000 }), 'Start free with ₦2,000 of chat credit. No card, no time limit.')
  assert.equal(creditLine({ starter_credit_ngn: 1500 }), 'Start free with ₦1,500 of chat credit. No card, no time limit.')
  assert.equal(creditLine({ starter_credit_ngn: 0 }), 'Start free. No card needed.')
  assert.equal(creditLine(null), 'Start free. No card needed.')
})

test('the plan line shows only what is priced and set', () => {
  assert.equal(planLine({ label: 'Chioma', monthly_ngn: 0 }), 'When your credit runs out, you can top up whenever you like.')
  assert.equal(planLine(null), 'When your credit runs out, you can top up whenever you like.')
  assert.equal(
    planLine({ label: 'Chioma', monthly_ngn: 15000, included_credit_ngn: 6000, ai_messages: 300 }),
    'When your credit runs out, choose the Chioma plan at ₦15,000 a month, which includes ₦6,000 of chat credit and 300 AI answers every month, or top up as you go.',
  )
  assert.equal(
    planLine({ label: 'Chioma', monthly_ngn: 15000 }),
    'When your credit runs out, choose the Chioma plan at ₦15,000 a month, or top up as you go.',
  )
})

test('naira formatting', () => {
  assert.equal(naira(15000), '₦15,000')
  assert.equal(naira(undefined), '₦0')
})
