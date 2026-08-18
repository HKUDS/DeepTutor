"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { KeyRound } from "lucide-react";
import Modal from "@/components/common/Modal";
import PageIndexConfigForm from "./PageIndexConfigForm";

interface PageIndexSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Called after a successful save so callers can refresh provider state. */
  onSaved?: () => void;
}

export default function PageIndexSettingsModal({
  isOpen,
  onClose,
  onSaved,
}: PageIndexSettingsModalProps) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);

  return (
    <Modal
      isOpen={isOpen}
      onClose={saving ? () => {} : onClose}
      title={t("PageIndex settings")}
      titleIcon={<KeyRound size={16} />}
      width="md"
      closeOnBackdrop={!saving}
      closeOnEscape={!saving}
    >
      {isOpen && (
        <PageIndexConfigForm
          onChanged={onSaved}
          onSubmit={onClose}
          onCancel={onClose}
          onSavingChange={setSaving}
        />
      )}
    </Modal>
  );
}
