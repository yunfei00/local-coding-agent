export type OrderedToolChunk = {
  stream: "stdout" | "stderr";
  text: string;
  sequence: number;
};

export type ToolChunkMergeResult = {
  chunks: OrderedToolChunk[];
  droppedChars: number;
};

export function appendOrderedToolChunk(
  chunks: OrderedToolChunk[],
  nextChunk: OrderedToolChunk,
  maxChars = 60000
): ToolChunkMergeResult {
  const bySequence = new Map<number, OrderedToolChunk>();
  for (const chunk of chunks) {
    bySequence.set(chunk.sequence, chunk);
  }
  bySequence.set(nextChunk.sequence, nextChunk);

  const ordered = [...bySequence.values()].sort(
    (left, right) => left.sequence - right.sequence
  );

  let total = ordered.reduce((sum, item) => sum + item.text.length, 0);
  let droppedChars = 0;

  while (ordered.length > 1 && total > maxChars) {
    const removed = ordered.shift();
    const removedLength = removed?.text.length ?? 0;
    total -= removedLength;
    droppedChars += removedLength;
  }

  if (ordered.length === 1 && total > maxChars) {
    const only = ordered[0];
    const keep = only.text.slice(-maxChars);
    droppedChars += only.text.length - keep.length;
    ordered[0] = { ...only, text: keep };
  }

  return {
    chunks: ordered,
    droppedChars
  };
}
