import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusBadge from "../StatusBadge";
import { STATUS_COLORS } from "../../constants";

describe("StatusBadge", () => {
  // --- All 10+ defined statuses render with correct colors ---

  const definedStatuses = Object.keys(STATUS_COLORS);

  it.each(definedStatuses)("renders '%s' status with correct color classes", (status) => {
    render(<StatusBadge status={status} />);
    const label = status.replace(/_/g, " ");
    const badge = screen.getByText(label);
    expect(badge).toBeInTheDocument();

    const expectedClasses = STATUS_COLORS[status];
    for (const cls of expectedClasses.split(" ")) {
      expect(badge.className).toContain(cls);
    }
  });

  // --- Specific status-color spot checks ---

  it("renders queued with gray colors", () => {
    render(<StatusBadge status="queued" />);
    const badge = screen.getByText("queued");
    expect(badge.className).toContain("bg-gray-100");
    expect(badge.className).toContain("text-gray-700");
  });

  it("renders in_progress with blue colors", () => {
    render(<StatusBadge status="in_progress" />);
    const badge = screen.getByText("in progress");
    expect(badge.className).toContain("bg-blue-100");
    expect(badge.className).toContain("text-blue-700");
  });

  it("renders replied_positive with green colors", () => {
    render(<StatusBadge status="replied_positive" />);
    const badge = screen.getByText("replied positive");
    expect(badge.className).toContain("bg-green-100");
    expect(badge.className).toContain("text-green-800");
  });

  it("renders replied_negative with red colors", () => {
    render(<StatusBadge status="replied_negative" />);
    const badge = screen.getByText("replied negative");
    expect(badge.className).toContain("bg-red-100");
    expect(badge.className).toContain("text-red-700");
  });

  it("renders no_response with yellow colors", () => {
    render(<StatusBadge status="no_response" />);
    const badge = screen.getByText("no response");
    expect(badge.className).toContain("bg-yellow-100");
    expect(badge.className).toContain("text-yellow-800");
  });

  it("renders bounced with red colors", () => {
    render(<StatusBadge status="bounced" />);
    const badge = screen.getByText("bounced");
    expect(badge.className).toContain("bg-red-100");
  });

  it("renders active with green colors", () => {
    render(<StatusBadge status="active" />);
    const badge = screen.getByText("active");
    expect(badge.className).toContain("bg-green-100");
    expect(badge.className).toContain("text-green-800");
  });

  it("renders completed with gray colors", () => {
    render(<StatusBadge status="completed" />);
    const badge = screen.getByText("completed");
    expect(badge.className).toContain("bg-gray-100");
  });

  it("renders drafted with blue colors", () => {
    render(<StatusBadge status="drafted" />);
    const badge = screen.getByText("drafted");
    expect(badge.className).toContain("bg-blue-100");
  });

  it("renders sent with green colors", () => {
    render(<StatusBadge status="sent" />);
    const badge = screen.getByText("sent");
    expect(badge.className).toContain("bg-green-100");
  });

  it("renders paused with amber colors", () => {
    render(<StatusBadge status="paused" />);
    const badge = screen.getByText("paused");
    expect(badge.className).toContain("bg-amber-100");
    expect(badge.className).toContain("text-amber-700");
  });

  // --- Label formatting ---

  it("replaces underscores with spaces in label", () => {
    render(<StatusBadge status="replied_positive" />);
    expect(screen.getByText("replied positive")).toBeInTheDocument();
    expect(screen.queryByText("replied_positive")).not.toBeInTheDocument();
  });

  it("replaces multiple underscores correctly", () => {
    render(<StatusBadge status="no_response" />);
    expect(screen.getByText("no response")).toBeInTheDocument();
  });

  it("handles single-word status without underscores", () => {
    render(<StatusBadge status="active" />);
    expect(screen.getByText("active")).toBeInTheDocument();
  });

  // --- Unknown status fallback ---

  it("renders unknown status with gray fallback colors", () => {
    render(<StatusBadge status="mystery_status" />);
    const badge = screen.getByText("mystery status");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("bg-gray-100");
    expect(badge.className).toContain("text-gray-700");
  });

  it("renders empty string status with fallback", () => {
    render(<StatusBadge status="" />);
    // Badge should exist but with empty text content
    const spans = document.querySelectorAll("span");
    expect(spans.length).toBeGreaterThan(0);
  });

  // --- Structure ---

  it("renders as a span element", () => {
    render(<StatusBadge status="queued" />);
    expect(screen.getByText("queued").tagName).toBe("SPAN");
  });

  it("has pill shape (rounded-full)", () => {
    render(<StatusBadge status="queued" />);
    expect(screen.getByText("queued").className).toContain("rounded-full");
  });

  it("has capitalize class for CSS text-transform", () => {
    render(<StatusBadge status="queued" />);
    expect(screen.getByText("queued").className).toContain("capitalize");
  });

  it("has inline-block display", () => {
    render(<StatusBadge status="queued" />);
    expect(screen.getByText("queued").className).toContain("inline-block");
  });

  it("has text-xs for small text", () => {
    render(<StatusBadge status="queued" />);
    expect(screen.getByText("queued").className).toContain("text-xs");
  });

  it("has font-medium weight", () => {
    render(<StatusBadge status="queued" />);
    expect(screen.getByText("queued").className).toContain("font-medium");
  });
});
