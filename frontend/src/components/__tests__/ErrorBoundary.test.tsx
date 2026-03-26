import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ErrorBoundary from "../ErrorBoundary";

// A component that throws when told to
function ThrowingChild({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error("Test explosion");
  }
  return <div>All good</div>;
}

// Silence console.error from React error boundary logging
beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("ErrorBoundary", () => {
  // --- Normal rendering ---

  it("renders children when no error occurs", () => {
    render(
      <ErrorBoundary>
        <div>Child content</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText("Child content")).toBeInTheDocument();
  });

  it("does not show error UI when children render normally", () => {
    render(
      <ErrorBoundary>
        <div>Normal rendering</div>
      </ErrorBoundary>,
    );
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
  });

  it("renders multiple children without error", () => {
    render(
      <ErrorBoundary>
        <div>First child</div>
        <div>Second child</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText("First child")).toBeInTheDocument();
    expect(screen.getByText("Second child")).toBeInTheDocument();
  });

  // --- Error catching ---

  it("catches errors and shows fallback UI", () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText("All good")).not.toBeInTheDocument();
  });

  it("displays the error message", () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Test explosion")).toBeInTheDocument();
  });

  it("shows the Try again button in error state", () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  // --- Error message display ---

  it("displays custom error messages", () => {
    function CustomError() {
      throw new Error("Database connection failed");
    }
    render(
      <ErrorBoundary>
        <CustomError />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Database connection failed")).toBeInTheDocument();
  });

  it("displays long error messages", () => {
    const longMessage = "Error: " + "x".repeat(200);
    function LongError() {
      throw new Error(longMessage);
    }
    render(
      <ErrorBoundary>
        <LongError />
      </ErrorBoundary>,
    );
    expect(screen.getByText(longMessage)).toBeInTheDocument();
  });

  // --- Retry behavior ---

  it("recovers when Try again is clicked and child no longer throws", async () => {
    const user = userEvent.setup();
    let shouldThrow = true;

    function ConditionalThrow() {
      if (shouldThrow) throw new Error("Boom");
      return <div>Recovered successfully</div>;
    }

    render(
      <ErrorBoundary>
        <ConditionalThrow />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();

    // Fix the error condition before retrying
    shouldThrow = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(screen.getByText("Recovered successfully")).toBeInTheDocument();
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
  });

  it("shows error again if child still throws after retry", async () => {
    const user = userEvent.setup();

    function AlwaysThrows() {
      throw new Error("Persistent error");
    }

    render(
      <ErrorBoundary>
        <AlwaysThrows />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Persistent error")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Try again" }));

    // Should still show the error
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("Persistent error")).toBeInTheDocument();
  });

  // --- Styling ---

  it("error fallback has red background styling", () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>,
    );
    const heading = screen.getByText("Something went wrong");
    expect(heading.className).toContain("text-red-800");
  });

  it("Try again button has red button styling", () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>,
    );
    const button = screen.getByRole("button", { name: "Try again" });
    expect(button.className).toContain("bg-red-600");
  });

  it("error message has monospace font", () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>,
    );
    const msg = screen.getByText("Test explosion");
    expect(msg.className).toContain("font-mono");
  });
});
