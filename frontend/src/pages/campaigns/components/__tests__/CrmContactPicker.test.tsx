import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const mockListContacts = vi.fn();

vi.mock("../../../../api/contacts", () => ({
  contactsApi: {
    listContacts: (...args: unknown[]) => mockListContacts(...args),
  },
}));

vi.mock("../../../../hooks/useDebouncedValue", () => ({
  useDebouncedValue: <T,>(v: T) => v,
}));

vi.mock("../../../../components/ui/Input", () => ({
  default: (props: Record<string, unknown>) => (
    <input
      data-testid="search-input"
      placeholder={props.placeholder as string}
      value={props.value as string}
      onChange={props.onChange as React.ChangeEventHandler<HTMLInputElement>}
    />
  ),
}));

import CrmContactPicker from "../CrmContactPicker";

const CONTACTS = [
  { id: 1, full_name: "Alice Chen", first_name: "Alice", last_name: "Chen", company_name: "Alpha Fund", aum_millions: 500 },
  { id: 2, full_name: "Bob Smith", first_name: "Bob", last_name: "Smith", company_name: "Alpha Fund", aum_millions: 400 },
  { id: 3, full_name: "Carol Lee", first_name: "Carol", last_name: "Lee", company_name: "Beta Capital", aum_millions: 300 },
  { id: 4, full_name: "Dan Park", first_name: "Dan", last_name: "Park", company_name: "Beta Capital", aum_millions: 200 },
];

function renderPicker(selectedIds: Set<number>, onSelectionChange: (ids: Set<number>) => void) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CrmContactPicker selectedIds={selectedIds} onSelectionChange={onSelectionChange} />
    </QueryClientProvider>,
  );
}

describe("CrmContactPicker onePerCompany constraint", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockListContacts.mockResolvedValue({
      contacts: CONTACTS,
      pages: 1,
      total: CONTACTS.length,
    });
  });

  it("blocks clicking a contact from a company that already has a selected contact when onePerCompany is on", async () => {
    const user = userEvent.setup();
    // Alice (id=1) at Alpha Fund is already selected
    const selected = new Set([1]);
    const onChange = vi.fn();
    renderPicker(selected, onChange);

    // Wait for contacts to render
    await waitFor(() => {
      expect(screen.getByText("Alice Chen")).toBeInTheDocument();
    });

    // Enable one-per-company filter
    const filterButton = screen.getByText("One per company");
    await user.click(filterButton);

    // Reset mock to capture only the next call
    onChange.mockClear();

    // Try to click Bob Smith (also at Alpha Fund) — should be blocked
    const bobRow = screen.getByText("Bob Smith").closest("tr")!;
    await user.click(bobRow);

    // onChange should NOT have been called with Bob added
    const addedBob = onChange.mock.calls.some((call) => {
      const ids = call[0] as Set<number>;
      return ids.has(2);
    });
    expect(addedBob).toBe(false);
  });

  it("prunes duplicate-company selections when enabling onePerCompany filter", async () => {
    const user = userEvent.setup();
    // Both Alpha Fund contacts selected (violates one-per-company)
    const selected = new Set([1, 2, 3]);
    const onChange = vi.fn();
    renderPicker(selected, onChange);

    await waitFor(() => {
      expect(screen.getByText("Alice Chen")).toBeInTheDocument();
    });

    // Enable one-per-company — should prune duplicates
    const filterButton = screen.getByText("One per company");
    await user.click(filterButton);

    // onChange should have been called with a pruned set
    const pruneCall = onChange.mock.calls.find((call) => {
      const ids = call[0] as Set<number>;
      // Should keep only one contact from Alpha Fund (first seen = id 1)
      // and one from Beta Capital (id 3)
      return ids.size < 3;
    });
    expect(pruneCall).toBeDefined();
    const prunedIds = pruneCall![0] as Set<number>;
    // Should have kept Alice (1) from Alpha Fund and Carol (3) from Beta Capital
    expect(prunedIds.has(1)).toBe(true);
    expect(prunedIds.has(3)).toBe(true);
    // Bob (2) should have been pruned (same company as Alice)
    expect(prunedIds.has(2)).toBe(false);
  });

  it("allows clicking a contact from a different company when onePerCompany is on", async () => {
    const user = userEvent.setup();
    // Alice at Alpha Fund is selected
    const selected = new Set([1]);
    const onChange = vi.fn();
    renderPicker(selected, onChange);

    await waitFor(() => {
      expect(screen.getByText("Alice Chen")).toBeInTheDocument();
    });

    // Enable one-per-company filter
    const filterButton = screen.getByText("One per company");
    await user.click(filterButton);
    onChange.mockClear();

    // Click Carol Lee (Beta Capital, different company) — should be allowed
    const carolRow = screen.getByText("Carol Lee").closest("tr")!;
    await user.click(carolRow);

    const addedCarol = onChange.mock.calls.some((call) => {
      const ids = call[0] as Set<number>;
      return ids.has(3);
    });
    expect(addedCarol).toBe(true);
  });
});
