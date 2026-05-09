export function AssignedBadge({
  label = "Assigned by admin",
}: {
  label?: string;
}) {
  return (
    <span className="inline-flex items-center rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-300">
      {label}
    </span>
  );
}
