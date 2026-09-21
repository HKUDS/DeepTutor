import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import BookLibrary from '@/app/(workspace)/learning/books/components/BookLibrary'
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}))
it('a failed book list offers retry without claiming the library is empty', () => {
  const retry = vi.fn()
  render(
    <BookLibrary
      books={[]}
      loading={false}
      error="Failed to load books"
      onRetry={retry}
      canCreate={false}
      onNewBook={vi.fn()}
      onSelectBook={vi.fn()}
      onDeleteBook={vi.fn()}
    />
  )
  expect(screen.getByRole('alert')).toHaveTextContent('Failed to load books')
  expect(screen.queryByText('No books yet')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(retry).toHaveBeenCalledOnce()
})
