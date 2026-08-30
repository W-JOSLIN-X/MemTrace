import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { AppRoutes } from './App'

function renderApp(initialEntry = '/') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <AppRoutes />
    </MemoryRouter>,
  )
}

describe('MemTrace application shell', () => {
  it('renders the Day 6 conversation-first shell without pretending a task type is required', () => {
    renderApp()

    expect(
      screen.getByRole('heading', {
        name: '与 MemTrace 对话',
      }),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('对话内容')).toBeDisabled()
    expect(screen.queryByText('任务类型')).not.toBeInTheDocument()
    expect(screen.getByText('Day 6 · G5 · 真实模型')).toBeInTheDocument()
  })

  it('opens the Day 5 Memory Center', async () => {
    const user = userEvent.setup()
    renderApp()

    const desktopNavigation = screen.getByRole('navigation', {
      name: '主要导航',
    })
    await user.click(
      within(desktopNavigation).getByRole('link', { name: '记忆中心' }),
    )

    expect(
      screen.getByRole('heading', { name: '记忆中心' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/搜索、Diff、关系、冲突、匿名 Pack/),
    ).toBeInTheDocument()
  })

  it('redirects unknown routes to the chat page', () => {
    renderApp('/does-not-exist')

    expect(
      screen.getByRole('heading', {
        name: '与 MemTrace 对话',
      }),
    ).toBeInTheDocument()
  })
})
