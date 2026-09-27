import { Component, type ReactNode } from "react";

export class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="connection-screen" role="alert">
        <h1>The workspace needs to reload.</h1>
        <p>
          The engine may still be running. You can stop it from the tray menu.
        </p>
        <button className="primary-action" onClick={() => location.reload()}>
          Reload workspace
        </button>
      </div>
    );
  }
}
