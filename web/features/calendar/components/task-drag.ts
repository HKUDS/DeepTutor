/** Tasks travel between the rail, the day row and the grid as this drag type. */
export const TASK_DRAG_TYPE = 'application/x-deeptutor-task'

export function writeTaskDrag(transfer: DataTransfer, id: string) {
  transfer.setData(TASK_DRAG_TYPE, id)
  transfer.setData('text/plain', id)
  transfer.effectAllowed = 'copyMove'
}

export function readTaskDrag(transfer: DataTransfer): string | null {
  return transfer.getData(TASK_DRAG_TYPE) || null
}
