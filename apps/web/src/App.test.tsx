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
  it('renders the Day 4 G3 shell without pretending the Agent is connected', () => {
    renderApp()

    expect(
      screen.getByRole('heading', {
        name: '把编程问题交给 Agent，观察它如何完成任务',
      }),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Provider 模式：未连接')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '运行 Agent' })).toBeDisabled()
    expect(screen.getByText('G3 检索与注入流程')).toBeInTheDocument()
    expect(screen.getByText('Day 4 · G3')).toBeInTheDocument()
  })

  it('opens the minimal Day 4 memory lifecycle page', async () => {
    const user = userEvent.setup()
    renderApp()

    const desktopNavigation = screen.getByRole('navigation', {
      name: '主要导航',
    })
    await user.click(
      within(desktopNavigation).getByRole('link', { name: '记忆中心' }),
    )

    expect(
      screen.getByRole('heading', { name: '活跃记忆' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/搜索、合并与删除不在 Day 4 范围/),
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
