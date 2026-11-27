import assert from 'node:assert/strict'
import test from 'node:test'

import {
  DEFAULT_LAYOUT,
  L3_SLOTS,
  SURFACES,
  buildGraph,
  parseDoc,
  splitRef,
} from '../../lib/memory-graph'
import type {
  L1Entity,
  L3Slot,
  ParsedDoc,
  ParsedEntry,
  RawMemorySnapshot,
  Surface,
} from '../../lib/memory-graph'

// Entry ULIDs use the Crockford base32 subset [0-9A-HJKMNP-TV-Z]; tags are
// padded with "0" so every generated id satisfies the 26-char ENTRY_ID shape.
const entryId = (tag: string): string => `m_${tag}${'0'.repeat(26 - tag.length)}`

const entity = (id: string, label = id): L1Entity => ({
  id,
  label,
  ts: '2026-10-03T00:00:00Z',
  content: `content of ${label}`,
})

const emptySurfaceEntries = (): Record<Surface, ParsedEntry[]> => {
  const out = {} as Record<Surface, ParsedEntry[]>
  for (const s of SURFACES) out[s] = []
  return out
}

const emptyDocs = (): Record<Surface, ParsedDoc> => {
  const out = {} as Record<Surface, ParsedDoc>
  for (const s of SURFACES) out[s] = { title: '', entries: [] }
  return out
}

const emptySlotDocs = (): Record<L3Slot, ParsedDoc> => {
  const out = {} as Record<L3Slot, ParsedDoc>
  for (const slot of L3_SLOTS) out[slot] = { title: '', entries: [] }
  return out
}

const emptyL1 = (): Record<Surface, L1Entity[]> => {
  const out = {} as Record<Surface, L1Entity[]>
  for (const s of SURFACES) out[s] = []
  return out
}

const emptySnapshot = (): RawMemorySnapshot => ({
  l1: emptyL1(),
  l2: emptyDocs(),
  l3: emptySlotDocs(),
})

const parseLines = (...lines: string[]): ParsedDoc => parseDoc(lines.join('\n'))

// ── parseDoc ──────────────────────────────────────────────────────────

test('parseDoc: empty content yields an empty document', () => {
  assert.deepEqual(parseDoc(''), { title: '', entries: [] })
})

test('parseDoc: whitespace-only content yields no entries and no title', () => {
  const doc = parseDoc('\n\n   \n\t\n\r\n')
  assert.equal(doc.title, '')
  assert.deepEqual(doc.entries, [])
})

test('parseDoc: plain prose without bullets or footnotes is ignored', () => {
  const doc = parseDoc('Some intro text\n1. a numbered item\n> a quote\n---')
  assert.equal(doc.title, '')
  assert.deepEqual(doc.entries, [])
})

test('parseDoc: first H1 wins as title and later H1s are ignored', () => {
  const doc = parseLines('# First title', '# Second title', 'trailing prose')
  assert.equal(doc.title, 'First title')
  assert.deepEqual(doc.entries, [])
})

test('parseDoc: section headings annotate subsequent new-layout entries', () => {
  const id = entryId('A1')
  const doc = parseLines(
    '# Memory',
    '## Chat',
    `- asked about transformers [^1] <!--${id}-->`,
    '[^1]: chat:c_1'
  )
  assert.equal(doc.title, 'Memory')
  assert.equal(doc.entries.length, 1)
  assert.deepEqual(doc.entries[0], {
    id,
    section: 'Chat',
    text: 'asked about transformers',
    refs: ['chat:c_1'],
  })
})

test('parseDoc: multiple trailing markers resolve via the footnote table without duplicates', () => {
  const id = entryId('B2')
  const doc = parseLines(
    `- planned review [^1], [^2], [^1] <!--${id}-->`,
    '[^1]: chat:u_1',
    '[^2]: notebook:n_1'
  )
  assert.equal(doc.entries.length, 1)
  assert.deepEqual(doc.entries[0].refs, ['chat:u_1', 'notebook:n_1'])
})

test('parseDoc: footnote may appear after the bullet it resolves', () => {
  const id = entryId('C3')
  const doc = parseLines(`- deferred note [^1] <!--${id}-->`, '', '[^1]: kb:kb_9')
  assert.deepEqual(doc.entries[0].refs, ['kb:kb_9'])
})

test('parseDoc: legacy bullet with comma-separated footnote refs', () => {
  const id = entryId('D4')
  const doc = parseLines('## Quiz', `- legacy entry [^${id}]`, `[^${id}]: quiz:u_1, notebook:n_2`)
  assert.equal(doc.title, '')
  assert.deepEqual(doc.entries, [
    { id, section: 'Quiz', text: 'legacy entry', refs: ['quiz:u_1', 'notebook:n_2'] },
  ])
})

test('parseDoc: empty footnote payload resolves to no refs (marker dropped)', () => {
  const id = entryId('E5')
  // A degenerate footnote "[^1]:" stores [""]; the resolver filters empty
  // strings, so the entry ends up with no refs instead of a stub — the
  // same outcome as a legacy bullet whose footnote table is missing.
  const doc = parseLines(`- orphan marker [^1] <!--${id}-->`, '[^1]:')
  assert.deepEqual(doc.entries[0].refs, [])
})

test('parseDoc: unknown non-ULID label without a footnote is preserved as a stub', () => {
  const id = entryId('F6')
  const doc = parseLines(`- ghost marker [^ghost] <!--${id}-->`)
  assert.deepEqual(doc.entries[0].refs, ['ghost'])
})

test('parseDoc: legacy bullet with no footnote drops the unresolved entry id', () => {
  const id = entryId('G7')
  const doc = parseLines(`- unbacked legacy [^${id}]`)
  assert.equal(doc.entries.length, 1)
  assert.deepEqual(doc.entries[0].refs, [])
})

test('parseDoc: malformed bullet-like lines are skipped without throwing', () => {
  const doc = parseLines(
    '- a plain bullet with no marker',
    '- text [^short] with inline junk',
    '#### an h4 heading',
    '- text [^1] <!--truncated-marker-->',
    '[^1]: chat:c_1'
  )
  assert.deepEqual(doc.entries, [])
})

test('parseDoc: CRLF line endings are handled', () => {
  const id = entryId('H8')
  const doc = parseDoc(
    [`# Titled`, `- crlf entry [^1] <!--${id}-->`, `[^1]: book:b_1`].join('\r\n')
  )
  assert.equal(doc.title, 'Titled')
  assert.equal(doc.entries.length, 1)
  assert.equal(doc.entries[0].text, 'crlf entry')
  assert.deepEqual(doc.entries[0].refs, ['book:b_1'])
})

// ── splitRef ──────────────────────────────────────────────────────────

test('splitRef: splits a well-formed ref into surface and entity id', () => {
  assert.deepEqual(splitRef('chat:c_1'), { surface: 'chat', entityId: 'c_1' })
})

test('splitRef: keeps additional colons inside the entity id', () => {
  assert.deepEqual(splitRef('quiz:unified_x:q_1'), {
    surface: 'quiz',
    entityId: 'unified_x:q_1',
  })
})

test('splitRef: a bare surface with no colon yields an empty entity id', () => {
  assert.deepEqual(splitRef('chat'), { surface: 'chat', entityId: '' })
})

test('splitRef: empty ref yields empty surface and entity id', () => {
  assert.deepEqual(splitRef(''), { surface: '', entityId: '' })
})

test('splitRef: leading colon yields an empty surface', () => {
  assert.deepEqual(splitRef(':orphan'), { surface: '', entityId: 'orphan' })
})

test('splitRef: trailing colon yields an empty entity id', () => {
  assert.deepEqual(splitRef('chat:'), { surface: 'chat', entityId: '' })
})

// ── buildGraph ────────────────────────────────────────────────────────

test('buildGraph: empty snapshot produces anchors and clusters but no edges', () => {
  const graph = buildGraph(emptySnapshot())

  assert.equal(graph.edges.length, 0)
  assert.equal(graph.adjacency.size, 0)
  assert.equal(
    graph.clusters.length,
    L3_SLOTS.length + SURFACES.length * 2,
    'one L3 slot cluster plus an L2 and L1 cluster per surface'
  )
  // Synthetic hidden anchors exist for every surface even with no data.
  const anchors = graph.nodes.filter(n => n.id.endsWith(':__anchor__'))
  assert.equal(anchors.length, SURFACES.length)
  for (const anchor of anchors) {
    assert.equal(anchor.layer, 'L2')
    assert.equal(anchor.r, 0, 'anchors are hidden from hit-testing')
    assert.equal(
      graph.nodeCluster.get(anchor.id),
      `L2:${anchor.id.split(':')[1]}`,
      "anchors belong to their surface's L2 cluster"
    )
  }
  for (const cluster of graph.clusters) {
    assert.equal(cluster.count, 0)
    assert.ok(cluster.endAngle > cluster.startAngle, 'even empty slices stay labelable')
  }
})

test('buildGraph: cluster slices tile the full circle for every ring', () => {
  const graph = buildGraph(emptySnapshot())
  for (const layer of ['L1', 'L2', 'L3'] as const) {
    const gap = layer === 'L3' ? DEFAULT_LAYOUT.l3ClusterGap : DEFAULT_LAYOUT.clusterGap
    const total = graph.clusters
      .filter(c => c.layer === layer)
      .reduce((acc, c) => acc + (c.endAngle - c.startAngle + gap), 0)
    assert.ok(Math.abs(total - 2 * Math.PI) < 1e-9, `${layer} spans should cover 2π, got ${total}`)
  }
  assert.equal(new Set(graph.clusters.map(c => c.id)).size, graph.clusters.length)
})

test('buildGraph: L2 entry citing an L1 entity on another surface yields a strong cross-surface edge', () => {
  const snap = emptySnapshot()
  snap.l1.chat = [entity('c_1', 'Chat message')]
  const nbEntry = entryId('NB1')
  snap.l2.notebook = parseLines(
    '## Session',
    `- discussed the chat thread [^1] <!--${nbEntry}-->`,
    '[^1]: chat:c_1'
  )

  const graph = buildGraph(snap)
  const expected = {
    source: `L2:notebook:${nbEntry}`,
    target: 'L1:chat:c_1',
    kind: 'strong' as const,
  }
  assert.deepEqual(graph.edges, [expected])

  // Adjacency is symmetric and both endpoints are real nodes mapped to
  // their own clusters.
  for (const edge of graph.edges) {
    assert.ok(graph.adjacency.get(edge.source)?.includes(edge.target))
    assert.ok(graph.adjacency.get(edge.target)?.includes(edge.source))
    assert.ok(graph.nodes.some(n => n.id === edge.source))
    assert.ok(graph.nodes.some(n => n.id === edge.target))
  }
  assert.equal(graph.nodeCluster.get(expected.source), 'L2:notebook')
  assert.equal(graph.nodeCluster.get(expected.target), 'L1:chat')
  assert.equal(graph.clusters.find(c => c.id === 'L1:chat')?.count, 1)
})

test('buildGraph: L3 entry citing a bare surface yields a soft edge to that surface anchor', () => {
  const snap = emptySnapshot()
  const pEntry = entryId('P01')
  snap.l3.profile = parseLines(`- the learner lives in chat [^1] <!--${pEntry}-->`, '[^1]: chat')

  const graph = buildGraph(snap)
  assert.deepEqual(graph.edges, [
    { source: `L3:profile:${pEntry}`, target: 'L2:chat:__anchor__', kind: 'soft' },
  ])
  const anchor = graph.nodes.find(n => n.id === 'L2:chat:__anchor__')
  assert.ok(anchor, 'anchor node exists')
})

test('buildGraph: L3 entry citing a specific L2 entry id yields a strong edge', () => {
  const snap = emptySnapshot()
  const chatEntry = entryId('CM01')
  snap.l2.chat = parseLines(`- a chat consolidation [^1] <!--${chatEntry}-->`, '[^1]: chat:c_1')
  const rEntry = entryId('R001')
  snap.l3.recent = parseLines(
    `- revisit that consolidation [^1] <!--${rEntry}-->`,
    `[^1]: chat:${chatEntry}`
  )

  const graph = buildGraph(snap)
  assert.deepEqual(graph.edges, [
    {
      source: `L3:recent:${rEntry}`,
      target: `L2:chat:${chatEntry}`,
      kind: 'strong',
    },
  ])
})

test('buildGraph: duplicate surface citations from one L3 entry produce a single soft edge', () => {
  const snap = emptySnapshot()
  const entry: ParsedEntry = {
    id: entryId('DD01'),
    section: '',
    text: 'duplicated citation',
    refs: ['chat', 'chat'],
  }
  snap.l3.scope = { title: '', entries: [entry] }

  const graph = buildGraph(snap)
  assert.equal(graph.edges.length, 1)
  assert.equal(graph.edges[0].kind, 'soft')
  assert.equal(graph.edges[0].target, 'L2:chat:__anchor__')
})

test('buildGraph: invalid refs produce no edges and never throw', () => {
  const snap = emptySnapshot()
  snap.l1.chat = [entity('c_1')]
  const badEntry: ParsedEntry = {
    id: entryId('BAD1'),
    section: '',
    text: 'bad citations',
    // surface-only ref, unknown surface, and unknown L1 entity id
    refs: ['chat', 'bogus:x', 'notebook:n_ghost'],
  }
  snap.l2.notebook = { title: '', entries: [badEntry] }
  const badL3: ParsedEntry = {
    id: entryId('BAD2'),
    section: '',
    text: 'bad citations',
    refs: ['bogus', 'chat:m_MISSING'],
  }
  snap.l3.recent = { title: '', entries: [badL3] }

  const graph = buildGraph(snap)
  assert.deepEqual(graph.edges, [])
  assert.equal(graph.adjacency.size, 0)
})

test('buildGraph: duplicate L1 entity ids are deduped per surface', () => {
  const snap = emptySnapshot()
  snap.l1.quiz = [entity('u_1'), entity('u_1'), entity('u_2')]

  const graph = buildGraph(snap)
  const quizL1 = graph.nodes.filter(n => n.id.startsWith('L1:quiz:'))
  assert.equal(quizL1.length, 2)
  assert.equal(
    quizL1.filter(n => n.id === 'L1:quiz:u_1').length,
    1,
    'repeated snapshot rows for the same question id collapse into one node'
  )
  assert.equal(graph.clusters.find(c => c.id === 'L1:quiz')?.count, 2)
})

test('buildGraph: duplicate L2 entry ids are deduped per surface', () => {
  const snap = emptySnapshot()
  const id = entryId('DUP1')
  snap.l2.book = {
    title: '',
    entries: [
      { id, section: 'Ch.1', text: 'first', refs: [] },
      { id, section: 'Ch.2', text: 'second', refs: [] },
    ],
  }

  const graph = buildGraph(snap)
  const bookL2 = graph.nodes.filter(n => n.id === `L2:book:${id}`)
  assert.equal(bookL2.length, 1)
  assert.equal(graph.clusters.find(c => c.id === 'L2:book')?.count, 1)
})

test('buildGraph: custom layout options move the geometry center', () => {
  const opts = { ...DEFAULT_LAYOUT, width: 600, height: 400 }
  const graph = buildGraph(emptySnapshot(), opts)

  const anchor = graph.nodes.find(n => n.id === 'L2:chat:__anchor__')
  assert.ok(anchor)
  const midRingRadius = (opts.l2InnerRadius + opts.l2OuterRadius) / 2
  const distance = Math.hypot(anchor.x - opts.width / 2, anchor.y - opts.height / 2)
  assert.ok(
    Math.abs(distance - midRingRadius) < 1e-6,
    `anchor should sit on the L2 mid ring at radius ${midRingRadius}, got ${distance}`
  )
})

test('buildGraph: every node is placed inside the canvas and bookkeeping maps stay consistent', () => {
  const snap = emptySnapshot()
  snap.l1.chat = [entity('c_1'), entity('c_2')]
  snap.l1.notebook = [entity('n_1')]
  const nbEntry = entryId('NB01')
  snap.l2.notebook = parseLines(`- cites chat [^1] <!--${nbEntry}-->`, '[^1]: chat:c_1')
  const pEntry = entryId('P001')
  snap.l3.profile = parseLines(`- cites notebook [^1] <!--${pEntry}-->`, '[^1]: notebook')

  const graph = buildGraph(snap)
  const maxRadius = DEFAULT_LAYOUT.l1OuterRadius + 20

  assert.equal(new Set(graph.nodes.map(n => n.id)).size, graph.nodes.length, 'node ids are unique')
  for (const node of graph.nodes) {
    assert.ok(
      Number.isFinite(node.x) && Number.isFinite(node.y),
      `${node.id} has finite coordinates`
    )
    const distance = Math.hypot(
      node.x - DEFAULT_LAYOUT.width / 2,
      node.y - DEFAULT_LAYOUT.height / 2
    )
    assert.ok(distance <= maxRadius, `${node.id} sits inside the outer ring`)
    assert.ok(graph.nodeCluster.has(node.id), `${node.id} is mapped to a cluster`)
    const clusterIds = new Set(graph.clusters.map(c => c.id))
    assert.ok(clusterIds.has(node.cluster), `${node.id} references a real cluster`)
  }
  for (const edge of graph.edges) {
    assert.ok(graph.adjacency.get(edge.source)?.includes(edge.target))
    assert.ok(graph.adjacency.get(edge.target)?.includes(edge.source))
  }
  // L1 nodes carry a navigation href scoped to their surface.
  const chatNode = graph.nodes.find(n => n.id === 'L1:chat:c_1')
  assert.ok(chatNode?.href.includes('surface=chat'))
})
