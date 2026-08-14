"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export function LLMConfigurationDialog({
  open,
  onOpenChange,
  onConfigure,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfigure: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md"
        showCloseButton={false}
        onOpenAutoFocus={(event) => event.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle className="text-balance">先配置 LLM，才能开始对话</DialogTitle>
          <DialogDescription className="text-pretty">
            请在设置中填写 LLM 提供商、Base URL、API Key 和默认模型。配置完成后即可发送消息。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            暂不配置
          </Button>
          <Button type="button" onClick={onConfigure}>
            去配置 LLM
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
