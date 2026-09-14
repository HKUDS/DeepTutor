"use client";

/**
 * Role-aware quick-start chips on the home empty state (review round 3).
 *
 * Teachers/admins see teaching entry points (备课 / 出卷 / 班级学情); students
 * see learning entries (错题归因 / 互动课件). The chat chips prefill the
 * composer with the trigger sentence the skill would otherwise need the user
 * to know by heart; the link chips jump straight to the page. This kills the
 * "magic word" discovery problem without touching capability routing.
 */

import Link from "next/link";
import { useTranslation } from "react-i18next";
import { BookOpen, FileSpreadsheet, GraduationCap, Crosshair, BookMarked, Users } from "lucide-react";
import { useAuthStatus } from "@/hooks/useAuthStatus";

export default function HomeRoleChips({
  onPrefill,
}: {
  onPrefill: (text: string) => void;
}) {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const { role } = useAuthStatus();
  if (
    role !== "teacher" &&
    role !== "admin" &&
    role !== "student" &&
    role !== "parent"
  )
    return null;

  const chipClass =
    "inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--card)] px-3.5 py-1.5 text-[13px] text-[var(--muted-foreground)] transition-colors hover:border-teal-500/40 hover:text-[var(--foreground)]";

  if (role === "parent") {
    // 家长视角：家庭学情（children 白名单视图）+ 互动课件入口。
    const parentChips = [
      {
        key: "family",
        icon: <Users size={13} />,
        label: zh ? "我的孩子" : "My children",
        href: "/family",
      },
      {
        key: "book",
        icon: <BookMarked size={13} />,
        label: zh ? "互动课件" : "Interactive books",
        href: `/${"book"}`,
      },
    ];
    return (
      <div className="mb-6 flex w-full max-w-[960px] flex-wrap items-center justify-center gap-2">
        {parentChips.map((chip) => (
          <Link key={chip.key} href={chip.href} className={chipClass}>
            {chip.icon}
            {chip.label}
          </Link>
        ))}
      </div>
    );
  }

  const isTeacher = role === "teacher" || role === "admin";
  const chips = isTeacher
    ? [
        {
          key: "prep",
          icon: <BookOpen size={13} />,
          label: zh ? "备课" : "Prepare lesson",
          onClick: () =>
            onPrefill(
              zh
                ? "帮我备课：教材《》，第 课，45 分钟"
                : "Help me prepare a lesson: textbook <>, chapter <>, 45 min",
            ),
        },
        {
          key: "review",
          icon: <GraduationCap size={13} />,
          label: zh ? "试卷分析" : "Analyze paper",
          onClick: () =>
            onPrefill(
              zh ? "帮我做丢分诊断和卷后分析" : "Run score diagnosis and paper review",
            ),
        },
        {
          key: "assemble",
          icon: <FileSpreadsheet size={13} />,
          label: zh ? "出卷" : "Assemble paper",
          href: "/space/questions?tab=exam_assemble",
        },
        {
          key: "class",
          icon: <GraduationCap size={13} />,
          label: zh ? "班级学情" : "Class insights",
          href: "/admin/class",
        },
      ]
      : [
          {
            key: "trace",
            icon: <Crosshair size={13} />,
            label: zh ? "错题归因" : "Trace errors",
            href: `/${"notebook"}`,
          },
          {
            key: "book",
            icon: <BookMarked size={13} />,
            label: zh ? "互动课件" : "Interactive books",
            href: `/${"book"}`,
          },
        ];

  return (
    <div className="mb-6 flex w-full max-w-[960px] flex-wrap items-center justify-center gap-2">
      {chips.map((chip) =>
        chip.href ? (
          <Link key={chip.key} href={chip.href} className={chipClass}>
            {chip.icon}
            {chip.label}
          </Link>
        ) : (
          <button key={chip.key} type="button" onClick={chip.onClick} className={chipClass}>
            {chip.icon}
            {chip.label}
          </button>
        ),
      )}
    </div>
  );
}
