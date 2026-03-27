import { Component, type ReactNode, type ErrorInfo } from "react";
import Button from "../../../components/ui/Button";

// --- Error Boundary (class component required) ---

interface ErrorBoundaryProps {
  children: ReactNode;
  onReset?: () => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class StepErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Wizard step error:", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm font-medium text-red-800 mb-2">Something went wrong in this step</p>
          <p className="text-xs text-red-600 mb-4">{this.state.error?.message}</p>
          <Button
            variant="secondary"
            onClick={() => {
              this.setState({ hasError: false, error: null });
              this.props.onReset?.();
            }}
          >
            Try again
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}

// --- Step Wrapper ---

interface WizardStepWrapperProps {
  children: ReactNode;
  currentStep: number;
  totalSteps: number;
  onNext: () => void;
  onBack: () => void;
  onSaveDraft: () => void;
  onLaunch: () => void;
  canProceed: boolean;
  isLaunching: boolean;
  isSaving: boolean;
}

export default function WizardStepWrapper({
  children,
  currentStep,
  totalSteps,
  onNext,
  onBack,
  onSaveDraft,
  onLaunch,
  canProceed,
  isLaunching,
  isSaving,
}: WizardStepWrapperProps) {
  const isFirst = currentStep === 0;
  const isLast = currentStep === totalSteps - 1;

  return (
    <StepErrorBoundary>
      <div className="min-h-[300px]">{children}</div>

      {/* Navigation footer */}
      <div className="flex items-center justify-between mt-8 pt-6 border-t border-gray-200">
        <div>
          {!isFirst && (
            <Button variant="secondary" onClick={onBack}>
              ← Back
            </Button>
          )}
        </div>

        <div className="flex items-center gap-3">
          {!isFirst && (
            <Button
              variant="secondary"
              onClick={onSaveDraft}
              disabled={isSaving}
            >
              {isSaving ? "Saving..." : "Save as Draft"}
            </Button>
          )}

          {isLast ? (
            <Button
              onClick={onLaunch}
              disabled={!canProceed || isLaunching}
            >
              {isLaunching ? (
                <span className="flex items-center gap-2">
                  <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Launching...
                </span>
              ) : (
                "Launch Campaign"
              )}
            </Button>
          ) : (
            <Button
              onClick={onNext}
              disabled={!canProceed}
            >
              Next →
            </Button>
          )}
        </div>
      </div>
    </StepErrorBoundary>
  );
}
