import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import HealthScoreBadge from "../HealthScoreBadge";

describe("HealthScoreBadge", () => {
  // --- Green tier (score >= 70) ---

  it("renders green badge for score of 100", () => {
    render(<HealthScoreBadge score={100} />);
    const badge = screen.getByText("100");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("bg-green-100");
    expect(badge.className).toContain("text-green-800");
  });

  it("renders green badge for score of 70 (boundary)", () => {
    render(<HealthScoreBadge score={70} />);
    const badge = screen.getByText("70");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("bg-green-100");
  });

  it("renders green badge for score of 85", () => {
    render(<HealthScoreBadge score={85} />);
    expect(screen.getByText("85").className).toContain("bg-green-100");
  });

  // --- Amber tier (40 <= score < 70) ---

  it("renders amber badge for score of 69 (boundary)", () => {
    render(<HealthScoreBadge score={69} />);
    const badge = screen.getByText("69");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("bg-amber-100");
    expect(badge.className).toContain("text-amber-800");
  });

  it("renders amber badge for score of 40 (boundary)", () => {
    render(<HealthScoreBadge score={40} />);
    const badge = screen.getByText("40");
    expect(badge.className).toContain("bg-amber-100");
  });

  it("renders amber badge for score of 55", () => {
    render(<HealthScoreBadge score={55} />);
    expect(screen.getByText("55").className).toContain("bg-amber-100");
  });

  // --- Red tier (score < 40) ---

  it("renders red badge for score of 39 (boundary)", () => {
    render(<HealthScoreBadge score={39} />);
    const badge = screen.getByText("39");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("bg-red-100");
    expect(badge.className).toContain("text-red-800");
  });

  it("renders red badge for score of 0", () => {
    render(<HealthScoreBadge score={0} />);
    expect(screen.getByText("0").className).toContain("bg-red-100");
  });

  it("renders red badge for score of 1", () => {
    render(<HealthScoreBadge score={1} />);
    expect(screen.getByText("1").className).toContain("bg-red-100");
  });

  // --- N/A states ---

  it("renders N/A when score is null", () => {
    render(<HealthScoreBadge score={null} />);
    const badge = screen.getByText("N/A");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("bg-gray-100");
    expect(badge.className).toContain("text-gray-500");
  });

  it("renders N/A when score is undefined", () => {
    render(<HealthScoreBadge />);
    expect(screen.getByText("N/A")).toBeInTheDocument();
  });

  it("renders N/A with no score prop at all", () => {
    render(<HealthScoreBadge score={undefined} />);
    expect(screen.getByText("N/A").className).toContain("bg-gray-100");
  });

  // --- Structure ---

  it("renders as an inline span", () => {
    render(<HealthScoreBadge score={50} />);
    const badge = screen.getByText("50");
    expect(badge.tagName).toBe("SPAN");
  });

  it("has rounded-full class for pill shape", () => {
    render(<HealthScoreBadge score={50} />);
    expect(screen.getByText("50").className).toContain("rounded-full");
  });

  it("has font-semibold class", () => {
    render(<HealthScoreBadge score={50} />);
    expect(screen.getByText("50").className).toContain("font-semibold");
  });

  it("has text-xs class for small text", () => {
    render(<HealthScoreBadge score={50} />);
    expect(screen.getByText("50").className).toContain("text-xs");
  });

  // --- Edge cases ---

  it("displays exact numeric score value", () => {
    render(<HealthScoreBadge score={42} />);
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.queryByText("N/A")).not.toBeInTheDocument();
  });

  it("does not render N/A when score is 0 (falsy but defined)", () => {
    render(<HealthScoreBadge score={0} />);
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.queryByText("N/A")).not.toBeInTheDocument();
  });
});
