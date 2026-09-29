export type ComposerKey = {
  key: string;
  shiftKey: boolean;
  isComposing: boolean;
};

export function shouldSubmitComposer(input: ComposerKey): boolean {
  return input.key === "Enter" && !input.shiftKey && !input.isComposing;
}
