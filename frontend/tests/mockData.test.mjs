import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeCorpus, normalizePrices } from '../src/api/mockData.js'


test('normalizes exported document chunks into searchable passages', () => {
  const passages = normalizeCorpus([
    {
      id: 38,
      title: '技术路线',
      chunks: [
        {
          chunk_id: 440,
          content: '纯电与增程的主要区别。',
          heading_path: '技术路线 > 对比',
          page_no: 2,
        },
      ],
    },
  ])

  assert.deepEqual(passages, [
    {
      docId: 38,
      title: '技术路线',
      text: '纯电与增程的主要区别。',
      chunkId: 440,
      page: 2,
      headingPath: '技术路线 > 对比',
    },
  ])
})


test('keeps compatibility with the legacy passages envelope', () => {
  const passages = normalizeCorpus({
    passages: [{ docId: 1, chunkId: 2, title: '政策', text: '购置税政策' }],
  })

  assert.equal(passages.length, 1)
  assert.equal(passages[0].text, '购置税政策')
})


test('normalizes exported price rows to the live API contract', () => {
  const prices = normalizePrices([
    {
      brand_name: '五菱',
      series_name: '五菱宏光MINIEV',
      segment: '微型车',
      endurance_km: 170,
      guide_price_min: 3.28,
      guide_price_max: 9.99,
    },
  ])

  assert.deepEqual(prices, [
    {
      brand: '五菱',
      series: '五菱宏光MINIEV',
      segment: '微型车',
      endurance: 170,
      min: 3.28,
      max: 9.99,
      priceText: '3.28-9.99万',
      descender: 0,
    },
  ])
})
