import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ServerFolderPicker } from '@/components/workspaces/ServerFolderPicker'

const fixture = vi.hoisted(() => ({ browse: vi.fn() }))
vi.mock('@/lib/workspaces-api', () => ({ browseServerFolders: fixture.browse }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

const roots = [{ name: 'src', path: '/home/user/src' }]
const page = (path: string, folders: { name: string; path: string }[]) => ({
  roots,
  path,
  name: path.split('/').pop(),
  parent: path === roots[0].path ? null : path.slice(0, path.lastIndexOf('/')),
  folders,
  truncated: false,
})

it('opens folders, returns to the parent and selects the visible server folder without typing paths', async () => {
  fixture.browse.mockImplementation(async (path: string) =>
    path === '/home/user/src/oss'
      ? page(path, [{ name: 'flashinfer', path: '/home/user/src/oss/flashinfer' }])
      : path === '/home/user/src/oss/flashinfer'
        ? page(path, [])
        : page(roots[0].path, [{ name: 'oss', path: '/home/user/src/oss' }])
  )
  const select = vi.fn()
  const close = vi.fn()
  render(<ServerFolderPicker onClose={close} onSelect={select} />)
  fireEvent.click(await screen.findByRole('button', { name: 'oss' }))
  fireEvent.click(await screen.findByRole('button', { name: 'flashinfer' }))
  await screen.findByText('No subfolders')
  expect(screen.getByLabelText('Current folder')).toHaveTextContent('/home/user/src/oss/flashinfer')
  fireEvent.click(screen.getByRole('button', { name: 'Parent folder' }))
  fireEvent.click(await screen.findByRole('button', { name: 'flashinfer' }))
  await screen.findByText('No subfolders')
  fireEvent.click(screen.getByRole('button', { name: 'Select this folder' }))
  await waitFor(() =>
    expect(select).toHaveBeenCalledWith({
      name: 'flashinfer',
      path: '/home/user/src/oss/flashinfer',
    })
  )
  await waitFor(() => expect(close).toHaveBeenCalled())
})

it('keeps a failed folder load unselectable and allows retry', async () => {
  fixture.browse
    .mockRejectedValueOnce(new Error('Cannot open folder'))
    .mockResolvedValue(page(roots[0].path, []))
  render(<ServerFolderPicker onClose={vi.fn()} onSelect={vi.fn()} />)
  await screen.findByRole('alert')
  expect(screen.getByRole('button', { name: 'Select this folder' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await screen.findByText('No subfolders')
  expect(screen.getByRole('button', { name: 'Select this folder' })).toBeEnabled()
})

it('recognizes a Windows server root while navigating its child folders', async () => {
  fixture.browse.mockResolvedValue({
    roots: [
      { name: 'Projects', path: 'D:\\Projects' },
      { name: 'Other', path: 'E:\\Other' },
    ],
    path: 'D:\\Projects\\Example',
    name: 'Example',
    parent: 'D:\\Projects',
    folders: [],
    truncated: false,
  })
  render(<ServerFolderPicker onClose={vi.fn()} onSelect={vi.fn()} />)
  expect(await screen.findByRole('combobox', { name: 'Browse root' })).toHaveValue('D:\\Projects')
})
