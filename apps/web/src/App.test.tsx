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
  it('renders the Day 1 chat shell without pretending the Agent is connected', () => {
    renderApp()

    expect(
      screen.getByRole('heading', {
        name: '把编程问题交给 Agent，观察它如何完成任务',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('尚未连接')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '接入后即可运行' })).toBeDisabled()
    expect(screen.getByText('尚无长期记忆')).toBeInTheDocument()
  })

  it('shows an honest placeholder on future routes', async () => {
    const user = userEvent.setup()
    renderApp()

    const desktopNavigation = screen.getByRole('navigation', {
      name: '主要导航',
    })
    await user.click(
      within(desktopNavigation).getByRole('link', { name: '记忆中心' }),
    )

    expect(
      screen.getByRole('heading', { name: '记忆中心将在 Day 5 实现' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/当前只是明确的功能占位/),
    ).toBeInTheDocument()
  })

  it('redirects unknown routes to the chat page', () => {
    renderApp('/does-not-exist')

    expect(
      screen.getByRole('heading', {
        name: '把编程问题交给 Agent，观察它如何完成任务',
      }),
    ).toBeInTheDocument()
  })
})
