/** Account roles accepted by the local user store. Only admin grants elevation. */
export type AccountRole = "admin" | "teacher" | "student" | "user";

const LABEL_KEYS: Record<AccountRole, "Admin" | "Teacher" | "Student" | "User"> = {
  admin: "Admin",
  teacher: "Teacher",
  student: "Student",
  user: "User",
};

export function accountRoleLabelKey(role: AccountRole): string {
  return LABEL_KEYS[role];
}
