import { Component } from 'react'
import type { ReactNode } from 'react'

type Props = { children: ReactNode }
type State = { failed: boolean }

export class RouteErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(): void {
    // Intentionally avoid logging render errors because component props may
    // contain private conversation or memory text.
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children
    return (
      <section className="page-shell" role="alert">
        <div className="memory-detail">
          <p className="eyebrow">页面恢复</p>
          <h1>这个页面未能安全显示</h1>
          <p className="mt-2 text-sm text-slate-600">
            未保存的页面状态已停止使用。重新载入后将从服务端权威快照恢复。
          </p>
          <button className="mt-4" onClick={() => globalThis.location.reload()} type="button">
            重新载入
          </button>
        </div>
      </section>
    )
  }
}
