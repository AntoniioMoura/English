// Mostra `text` comparado com `base` (diff por palavras, via LCS): palavras novas ficam
// destacadas e palavras removidas aparecem riscadas. Maiúsculas e pontuação não contam.

type Op = "same" | "added" | "removed";

const key = (word: string) => word.toLowerCase().replace(/[’‘]/g, "'").replace(/[^\w']/g, "");

function diffWords(base: string[], text: string[]): { word: string; op: Op }[] {
  const a = base.map(key);
  const b = text.map(key);
  const lcs = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const result: { word: string; op: Op }[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      result.push({ word: text[j], op: "same" });
      i++;
      j++;
    } else if (j < b.length && (i >= a.length || lcs[i][j + 1] >= lcs[i + 1][j])) {
      result.push({ word: text[j], op: "added" });
      j++;
    } else {
      result.push({ word: base[i], op: "removed" });
      i++;
    }
  }
  return result;
}

export function DiffText({ base, text }: { base: string; text: string }) {
  const split = (s: string) => s.split(/\s+/).filter(Boolean);
  const ops = diffWords(split(base), split(text));

  // Agrupa palavras vizinhas com a mesma operação para o destaque ficar contínuo.
  const groups: { text: string; op: Op }[] = [];
  for (const { word, op } of ops) {
    const last = groups[groups.length - 1];
    if (last && last.op === op) last.text += " " + word;
    else groups.push({ text: word, op });
  }

  return (
    <>
      {groups.map((g, idx) => (
        <span key={idx}>
          {idx > 0 && " "}
          {g.op === "added" && <mark className="diff-mark">{g.text}</mark>}
          {g.op === "removed" && <del className="diff-del">{g.text}</del>}
          {g.op === "same" && g.text}
        </span>
      ))}
    </>
  );
}
