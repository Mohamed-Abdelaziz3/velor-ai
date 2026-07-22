import { Component } from 'react';

class ErrorBoundary extends Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, errorInfo) {
        console.error('ErrorBoundary caught an error:', error, errorInfo);
    }

    handleRetry = () => {
        this.setState({ hasError: false, error: null });
        window.location.reload();
    };

    render() {
        if (this.state.hasError) {
            return (
                <div
                    dir="rtl"
                    className="min-h-screen bg-velor-deep velor-grid-bg flex items-center justify-center px-4"
                >
                    <div className="velor-panel bg-velor-panel/90 backdrop-blur-xl p-8 sm:p-10 max-w-lg w-full text-center">
                        {/* Error Icon */}
                        <div className="mx-auto mb-6 w-20 h-20 rounded-full bg-red-500/10 border border-red-500/30 flex items-center justify-center">
                            <svg
                                className="w-10 h-10 text-red-400"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                            >
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                                />
                            </svg>
                        </div>

                        <h1 className="text-2xl font-bold text-slate-100 mb-3">
                            حدث خطأ غير متوقع
                        </h1>
                        <p className="text-slate-400 mb-8 leading-relaxed">
                            نعتذر عن هذا الخطأ. يرجى المحاولة مرة أخرى أو التواصل مع فريق الدعم إذا استمرت المشكلة.
                        </p>

                        {this.state.error && (
                            <details className="bg-black/20 border border-white/10 rounded-lg p-4 mb-8 text-left">
                                <summary className="cursor-pointer text-xs text-velor-muted">تفاصيل تقنية</summary>
                                <p className="text-red-400 text-sm font-sans break-all">
                                    {this.state.error.toString()}
                                </p>
                            </details>
                        )}

                        <button
                            onClick={this.handleRetry}
                            className="velor-button-primary px-8"
                        >
                            إعادة المحاولة
                        </button>
                    </div>
                </div>
            );
        }

        return this.props.children;
    }
}

export default ErrorBoundary;
