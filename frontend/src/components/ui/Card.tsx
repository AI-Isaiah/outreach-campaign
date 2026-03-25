import type { ReactNode, HTMLAttributes } from "react";

const paddingClasses = {
  none: "",
  sm: "p-4",
  md: "p-5",
  lg: "p-6",
} as const;

const accentBorderClasses: Record<string, string> = {
  green: "border-l-4 border-l-green-400",
  blue: "border-l-4 border-l-blue-400",
  yellow: "border-l-4 border-l-yellow-400",
  red: "border-l-4 border-l-red-400",
  gray: "border-l-4 border-l-gray-200",
};

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: keyof typeof paddingClasses;
  hover?: boolean;
  accentBorder?: string;
  children: ReactNode;
}

function Card({
  padding = "md",
  hover = false,
  accentBorder,
  children,
  className = "",
  ...props
}: CardProps) {
  return (
    <div
      className={[
        "bg-white rounded-xl border border-gray-200 shadow-sm",
        paddingClasses[padding],
        hover ? "hover:shadow-md transition-shadow duration-200" : "",
        accentBorder && accentBorderClasses[accentBorder]
          ? accentBorderClasses[accentBorder]
          : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      {...props}
    >
      {children}
    </div>
  );
}

function CardHeader({
  children,
  className = "",
  ...props
}: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div
      className={`px-5 py-4 border-b border-gray-100 ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

function CardBody({
  children,
  className = "",
  ...props
}: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div className={`p-5 ${className}`} {...props}>
      {children}
    </div>
  );
}

function CardFooter({
  children,
  className = "",
  ...props
}: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div
      className={`px-5 py-3 border-t border-gray-100 ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

Card.Header = CardHeader;
Card.Body = CardBody;
Card.Footer = CardFooter;

export default Card;
