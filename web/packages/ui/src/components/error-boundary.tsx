"use client";

import { Component } from "react";
import { unstable_rethrow } from "next/navigation";
import type { ErrorInfo } from "react";
import { AlertCircle, RotateCw } from "lucide-react";

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
  /** report the caught error. kept as a prop so this package stays free of any
      error-tracking dependency — www consumes it too and is not instrumented. */
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.props.onError?.(error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      // notFound() and redirect() are thrown too; they belong to next's own boundaries
      unstable_rethrow(this.state.error);
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="flex flex-col items-center justify-center gap-4 py-24">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-danger/10">
            <AlertCircle size={24} className="text-danger" />
          </div>
          <div className="flex flex-col items-center gap-1.5">
            <span className="font-heading text-base font-bold text-text-primary">
              Something went wrong
            </span>
            <span className="max-w-md text-center text-[13px] text-text-secondary">
              {this.state.error?.message || "An unexpected error occurred"}
            </span>
          </div>
          <button
            onClick={this.handleRetry}
            className="flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-[13px] font-medium text-text-secondary transition-colors hover:border-text-dim hover:text-text-primary"
          >
            <RotateCw size={14} />
            <span>Try again</span>
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
