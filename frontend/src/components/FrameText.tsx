// Destaca as lacunas "___" da Sentence Frame.
export function FrameText({ text, large = false }: { text: string; large?: boolean }) {
  const parts = text.split("___");
  return (
    <span className={`frame-text ${large ? "frame-text-large" : ""}`}>
      {parts.map((part, i) => (
        <span key={i}>
          {part}
          {i < parts.length - 1 && <span className="blank">&nbsp;</span>}
        </span>
      ))}
    </span>
  );
}
