import { useId, type ReactElement, type ReactNode } from "react";
import { cloneElement } from "react";
import { cn } from "./styles";

export interface FieldProps {
  label: string;
  children: ReactElement<{
    id?: string;
    "aria-describedby"?: string;
    "aria-invalid"?: boolean;
  }>;
  hint?: ReactNode;
  error?: ReactNode;
  optionalLabel?: string;
  className?: string;
}

export function Field({
  label,
  children,
  hint,
  error,
  optionalLabel,
  className,
}: FieldProps) {
  const generatedId = useId();
  const controlId = children.props.id ?? generatedId;
  const hintId = `${generatedId}-hint`;
  const errorId = `${generatedId}-error`;
  const describedBy = [
    children.props["aria-describedby"],
    hint ? hintId : undefined,
    error ? errorId : undefined,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={cn("grid gap-1.5", className)}>
      <label
        htmlFor={controlId}
        className="text-sm font-medium text-foreground"
      >
        {label}
        {optionalLabel ? (
          <span className="ml-1 font-normal text-muted-foreground">
            {optionalLabel}
          </span>
        ) : null}
      </label>
      {cloneElement(children, {
        id: controlId,
        "aria-describedby": describedBy || undefined,
        "aria-invalid": error ? true : children.props["aria-invalid"],
      })}
      {hint ? (
        <p id={hintId} className="text-xs leading-5 text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p
          id={errorId}
          className="text-xs font-medium leading-5 text-destructive"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}
