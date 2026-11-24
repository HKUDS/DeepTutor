import { PageCustomizationProvider } from "@/context/PageCustomizationContext";
import TaskBoardRuntime from "@/components/tasks/TaskBoardRuntime";

export default function WorkspaceLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <PageCustomizationProvider>
      {/* Inside WorkspaceRuntimeBoundary (from parent shell): each workspace owns its board sync. */}
      <TaskBoardRuntime>{children}</TaskBoardRuntime>
    </PageCustomizationProvider>
  );
}
