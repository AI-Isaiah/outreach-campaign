import { forwardRef, type SelectHTMLAttributes } from "react";

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  helpText?: string;
}

const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, error, helpText, id, children, className = "", ...props }, ref) => {
    const selectId =
      id || (label ? label.toLowerCase().replace(/\s+/g, "-") : undefined);

    return (
      <div className="space-y-1">
        {label && (
          <label
            htmlFor={selectId}
            className="block text-sm font-medium text-gray-700"
          >
            {label}
          </label>
        )}
        <select
          ref={ref}
          id={selectId}
          className={[
            "block w-full rounded-lg border text-sm bg-white transition-colors appearance-none",
            "focus:outline-none focus:ring-2 focus:ring-offset-0",
            "disabled:bg-gray-50 disabled:text-gray-500 disabled:cursor-not-allowed",
            error
              ? "border-red-300 focus:ring-red-500 focus:border-red-500"
              : "border-gray-200 focus:ring-blue-500 focus:border-blue-500",
            "pl-3 pr-8 py-2",
            className,
          ]
            .filter(Boolean)
            .join(" ")}
          style={{
            backgroundImage: `url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%236b7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e")`,
            backgroundPosition: "right 0.5rem center",
            backgroundRepeat: "no-repeat",
            backgroundSize: "1.25em 1.25em",
          }}
          {...props}
        >
          {children}
        </select>
        {error && <p className="text-xs text-red-600">{error}</p>}
        {!error && helpText && (
          <p className="text-xs text-gray-500">{helpText}</p>
        )}
      </div>
    );
  },
);

Select.displayName = "Select";

export default Select;
