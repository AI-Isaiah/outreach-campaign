import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import SignalBadge from "../SignalBadge";

const signal = (text: string, type = "fund_raise", score = 0.9) => ({
  type,
  text,
  recency_score: score,
});

describe("SignalBadge", () => {
  it("renders null when signals is empty", () => {
    const { container } = render(<SignalBadge signals={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders null when signals is undefined", () => {
    const { container } = render(<SignalBadge signals={undefined as any} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the top signal text", () => {
    render(<SignalBadge signals={[signal("Raised $200M new fund")]} />);
    expect(screen.getByText("Raised $200M new fund")).toBeInTheDocument();
  });

  it("truncates text longer than 40 chars", () => {
    const longText = "This is a very long signal text that exceeds forty characters easily";
    render(<SignalBadge signals={[signal(longText)]} />);
    // aria-label has full text, but visible badge text is truncated
    const badge = screen.getByLabelText(longText);
    expect(badge.textContent).toContain("\u2026");
    expect(badge.textContent!.length).toBeLessThan(longText.length);
  });

  it("shows full text in tooltip on hover", async () => {
    const text = "Speaking at crypto conference next week, very important event";
    render(<SignalBadge signals={[signal(text)]} />);

    // Tooltip not visible initially
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    // Hover shows tooltip
    fireEvent.mouseEnter(screen.getByLabelText(text));
    expect(screen.getByRole("tooltip")).toHaveTextContent(text);

    // Mouse leave hides tooltip (after debounce)
    fireEvent.mouseLeave(screen.getByLabelText(text));
  });

  it("shows tooltip on focus for keyboard accessibility", () => {
    const text = "New CIO appointed at the firm";
    render(<SignalBadge signals={[signal(text)]} />);

    fireEvent.focus(screen.getByLabelText(text));
    expect(screen.getByRole("tooltip")).toHaveTextContent(text);
  });

  it("has aria-label with full text", () => {
    const text = "Just raised $500M for crypto allocation";
    render(<SignalBadge signals={[signal(text)]} />);
    expect(screen.getByLabelText(text)).toBeInTheDocument();
  });

  it("renders only the first signal when multiple provided", () => {
    render(
      <SignalBadge
        signals={[
          signal("First signal"),
          signal("Second signal"),
          signal("Third signal"),
        ]}
      />,
    );
    expect(screen.getByText("First signal")).toBeInTheDocument();
    expect(screen.queryByText("Second signal")).not.toBeInTheDocument();
  });

  it("is styled as a blue badge", () => {
    render(<SignalBadge signals={[signal("test")]} />);
    const badge = screen.getByLabelText("test");
    expect(badge.className).toContain("bg-blue-50");
    expect(badge.className).toContain("text-blue-700");
    expect(badge.className).toContain("border-blue-200");
  });

  it("is focusable for keyboard navigation", () => {
    render(<SignalBadge signals={[signal("test")]} />);
    expect(screen.getByLabelText("test")).toHaveAttribute("tabindex", "0");
  });

  it("does not truncate text at exactly 40 chars", () => {
    const exactly40 = "1234567890123456789012345678901234567890";
    render(<SignalBadge signals={[signal(exactly40)]} />);
    expect(screen.getByText(exactly40)).toBeInTheDocument();
  });
});
