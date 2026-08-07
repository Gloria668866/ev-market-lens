function passageFrom(raw = {}, doc = {}) {
  return {
    docId: raw.docId ?? raw.doc_id ?? doc.id ?? doc.doc_id,
    title: raw.title || doc.title || doc.filename || '',
    text: raw.text ?? raw.content ?? '',
    chunkId: raw.chunkId ?? raw.chunk_id ?? raw.id,
    page: raw.page ?? raw.page_no ?? null,
    headingPath: raw.headingPath ?? raw.heading_path ?? '',
  }
}

export function normalizeCorpus(raw) {
  const source = Array.isArray(raw)
    ? raw
    : Array.isArray(raw?.docs)
      ? raw.docs
      : Array.isArray(raw?.passages)
        ? raw.passages
        : []

  return source
    .flatMap((entry) => {
      if (Array.isArray(entry?.chunks)) {
        return entry.chunks.map((chunk) => passageFrom(chunk, entry))
      }
      return [passageFrom(entry)]
    })
    .filter((passage) => passage.text)
}

function priceText(min, max) {
  if (min != null && max != null) {
    return Number(min) === Number(max) ? `${min}万` : `${min}-${max}万`
  }
  if (min != null) return `${min}万起`
  if (max != null) return `最高${max}万`
  return '暂无报价'
}

export function normalizePrices(raw) {
  const source = Array.isArray(raw) ? raw : Array.isArray(raw?.items) ? raw.items : []
  return source.map((item) => {
    const min = item.min ?? item.guide_price_min ?? null
    const max = item.max ?? item.guide_price_max ?? null
    return {
      brand: item.brand ?? item.brand_name ?? '',
      series: item.series ?? item.series_name ?? '',
      segment: item.segment ?? '',
      endurance: item.endurance ?? item.endurance_km ?? null,
      min,
      max,
      priceText: item.priceText ?? item.price_text ?? priceText(min, max),
      descender: item.descender ?? item.descender_price ?? 0,
    }
  })
}
