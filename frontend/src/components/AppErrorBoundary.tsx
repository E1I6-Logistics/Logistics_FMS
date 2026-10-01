import { Component, type ErrorInfo, type ReactNode } from 'react'
import { reportClientIssue } from '../utils/clientLogger'

type Props = { children: ReactNode }
type State = { failed: boolean; errorId: string | null }

export default class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false, errorId: null }

  static getDerivedStateFromError(): State {
    return {
      failed: true,
      errorId: `FE-${Date.now().toString(36).toUpperCase()}`,
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    reportClientIssue('error', 'react_render_error', error, {
      error_id: this.state.errorId ?? 'unknown',
      component_stack: info.componentStack?.slice(0, 1500) ?? '',
    })
  }

  render() {
    if (!this.state.failed) return this.props.children

    return (
      <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#EEF2F6', fontFamily: 'sans-serif' }}>
        <section style={{ width: 420, maxWidth: 'calc(100% - 32px)', padding: 28, borderRadius: 12, background: '#fff', boxShadow: '0 8px 28px rgba(0,0,0,.12)', textAlign: 'center' }}>
          <h1 style={{ margin: 0, fontSize: 18 }}>관제 화면 오류</h1>
          <p style={{ color: '#667085', fontSize: 13, lineHeight: 1.6 }}>
            화면을 표시하는 중 오류가 발생했습니다. 오류 정보는 로그에 저장되었습니다.
          </p>
          <code style={{ display: 'block', marginBottom: 18, color: '#B42318' }}>{this.state.errorId}</code>
          <button onClick={() => window.location.reload()} style={{ padding: '9px 16px', border: 0, borderRadius: 7, background: '#1769C2', color: '#fff', fontWeight: 700, cursor: 'pointer' }}>
            화면 다시 불러오기
          </button>
        </section>
      </main>
    )
  }
}

