import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { recallApi, VocabEntry } from "../../recallApi";

const EMPTY = { english_text: "", translation_pt: "" };

// "tired, look for, have to" → três entradas. Vírgula ou quebra de linha separam.
const splitWords = (text: string) =>
  text
    .split(/[,\n;]/)
    .map((w) => w.trim())
    .filter(Boolean);

export function RecallWords() {
  const [words, setWords] = useState<VocabEntry[] | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState<{ id: number; english_text: string; translation_pt: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const items = splitWords(form.english_text);
  const isBatch = items.length > 1;

  const load = () => recallApi.vocabulary().then(setWords).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSummary(null);
    try {
      const result = await recallApi.addWords(
        isBatch
          ? items.map((english_text) => ({ english_text }))
          : [{ english_text: items[0], translation_pt: form.translation_pt || undefined }],
      );
      setForm(EMPTY);
      if (isBatch) {
        const added = `${result.created.length} palavra(s) adicionada(s).`;
        const skipped = result.skipped.map((s) => `“${s.english_text}” (${s.reason})`).join(", ");
        setSummary(skipped ? `${added} Puladas: ${skipped}.` : added);
      }
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function saveEdit() {
    if (!editing) return;
    await act(() =>
      recallApi.updateWord(editing.id, {
        english_text: editing.english_text,
        translation_pt: editing.translation_pt || null,
      }),
    );
    setEditing(null);
  }

  function remove(word: VocabEntry) {
    if (!window.confirm(`Excluir “${word.english_text}”? Os exercícios já feitos continuam no histórico.`)) return;
    act(() => recallApi.deleteWord(word.id));
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Minhas palavras</h1>
          <p className="muted">Palavras ou expressões curtas em inglês. O sentido em português é opcional.</p>
        </div>
        <Link to="/recall" className="btn btn-ghost">
          ← Anki Premium
        </Link>
      </div>

      <form className="card word-form" onSubmit={add}>
        <label className="field">
          <span>Inglês — uma ou várias, separadas por vírgula</span>
          <input
            required
            maxLength={1500}
            placeholder="tired, because, have to, look for"
            value={form.english_text}
            onChange={(e) => setForm({ ...form, english_text: e.target.value })}
          />
        </label>
        <label className="field">
          <span>Sentido (opcional)</span>
          <input
            maxLength={80}
            placeholder={isBatch ? "só para uma palavra" : "cansado"}
            disabled={isBatch}
            value={isBatch ? "" : form.translation_pt}
            onChange={(e) => setForm({ ...form, translation_pt: e.target.value })}
          />
        </label>
        <button type="submit" className="btn btn-primary" disabled={items.length === 0 || items.length > 50}>
          {isBatch ? `Adicionar ${items.length}` : "Adicionar"}
        </button>
      </form>
      {isBatch && (
        <p className="muted tiny">
          Com várias palavras, o sentido fica para a IA definir. Dá para informar depois em “Editar”.
        </p>
      )}

      {summary && <div className="alert alert-ok">{summary}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {words && words.length === 0 && <p className="muted">Nenhuma palavra cadastrada ainda.</p>}

      {words && words.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Palavra</th>
                <th>Sentido</th>
                <th className="num">Praticada</th>
                <th className="num">Usada</th>
                <th>Ativa</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {words.map((w) =>
                editing?.id === w.id ? (
                  <tr key={w.id}>
                    <td>
                      <input
                        className="inline-input"
                        value={editing.english_text}
                        onChange={(e) => setEditing({ ...editing, english_text: e.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        className="inline-input"
                        value={editing.translation_pt}
                        onChange={(e) => setEditing({ ...editing, translation_pt: e.target.value })}
                      />
                    </td>
                    <td colSpan={4} className="row end">
                      <button className="link small" onClick={() => setEditing(null)}>
                        Cancelar
                      </button>
                      <button className="btn btn-primary" onClick={saveEdit}>
                        Salvar
                      </button>
                    </td>
                  </tr>
                ) : (
                  <tr key={w.id} className={w.enabled ? "" : "row-disabled"}>
                    <td>
                      <strong>{w.english_text}</strong>
                    </td>
                    <td>{w.translation_pt ?? <span className="muted small">definido pela IA</span>}</td>
                    <td className="num">{w.times_used}</td>
                    <td className="num">{w.times_demonstrated}</td>
                    <td>
                      <input
                        type="checkbox"
                        checked={w.enabled}
                        aria-label={`Ativar ${w.english_text}`}
                        onChange={() => act(() => recallApi.updateWord(w.id, { enabled: !w.enabled }))}
                      />
                    </td>
                    <td className="row end">
                      <button
                        className="link small"
                        onClick={() =>
                          setEditing({ id: w.id, english_text: w.english_text, translation_pt: w.translation_pt ?? "" })
                        }
                      >
                        Editar
                      </button>
                      <button className="link small danger" onClick={() => remove(w)}>
                        Excluir
                      </button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted tiny">“Praticada”: frases geradas com a palavra. “Usada”: respostas em que você usou a palavra.</p>
    </div>
  );
}
