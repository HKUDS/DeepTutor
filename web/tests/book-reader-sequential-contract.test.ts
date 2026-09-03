import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const source = fs.readFileSync(
  path.resolve(process.cwd(), 'app/(workspace)/books/components/PageReader.tsx'),
  'utf8'
)

test('arrow keys consume the current chapter before turning pages', () => {
  const callbackStart = source.indexOf('const navigateSequentially')
  const callbackEnd = source.indexOf('useEffect', callbackStart)
  const callback = source.slice(callbackStart, callbackEnd)
  const scrollDecision = callback.indexOf('sequentialReadTarget')
  const pageTurn = callback.indexOf('onNavigate?.')

  assert.ok(callbackStart >= 0 && callbackEnd > callbackStart)
  assert.ok(scrollDecision >= 0 && pageTurn > scrollDecision)
})

test('turning backward lands at the end and forward lands at the start', () => {
  const previousBranchMatch = source.match(
    /direction\s*===\s*['"]previous['"]\s*&&\s*previousPage/
  )
  const nextBranchMatch = source.match(/direction\s*===\s*['"]next['"]\s*&&\s*nextPage/)

  assert.ok(previousBranchMatch)
  assert.ok(nextBranchMatch)

  const previousBranch = previousBranchMatch.index ?? -1
  const nextBranch = nextBranchMatch.index ?? -1
  const setPlacement = (
    branch: string,
    pageVariable: 'previousPage' | 'nextPage',
    placement: 'end' | 'start'
  ) =>
    new RegExp(
      `pendingScrollPlacements\\.set\\(\\s*scrollPlacementKey\\(bookId,\\s*${pageVariable}\\.id\\)\\s*,\\s*['"]${placement}['"]\\s*\\)`
    ).test(branch)

  assert.ok(previousBranch >= 0)
  assert.ok(nextBranch > previousBranch)
  const previousBranchSource = source.slice(previousBranch, nextBranch)
  const nextBranchSource = source.slice(nextBranch)

  assert.ok(setPlacement(previousBranchSource, 'previousPage', 'end'))
  assert.equal(setPlacement(previousBranchSource, 'nextPage', 'start'), false)
  assert.ok(setPlacement(nextBranchSource, 'nextPage', 'start'))
})

test('the reader exposes native chapter progress and keeps direct footer turns', () => {
  assert.ok(source.includes('<progress'))
  assert.ok(source.includes('max={100}'))
  assert.ok(source.includes('Chapter progress: {{percent}}%'))
  assert.ok(source.includes('onNavigate(page.id)'))
})
