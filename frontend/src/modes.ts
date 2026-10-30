// Registro de itens do menu inicial. Novos modos de estudo entram aqui.

export interface MenuEntry {
  id: string;
  title: string;
  description: string;
  path: string;
  icon: string;
  kind: "study_mode" | "tool";
  accent: "indigo" | "violet" | "green" | "amber";
}

export const MENU: MenuEntry[] = [
  {
    id: "sentence_builder",
    title: "Criador de frases",
    description: "Escolha uma estrutura, escreva sua frase e expanda-a em três rodadas.",
    path: "/builder",
    icon: "🧱",
    kind: "study_mode",
    accent: "indigo",
  },
  {
    id: "sentence_recall",
    title: "Anki Premium",
    description: "Traduza frases com as suas palavras e revise seus erros com repetição espaçada.",
    path: "/recall",
    icon: "🔁",
    kind: "study_mode",
    accent: "violet",
  },
  {
    id: "listening",
    title: "Listening com vídeos",
    description: "Assista aos seus vídeos em inglês e complete as palavras que faltam nas legendas.",
    path: "/listening",
    icon: "🎧",
    kind: "study_mode",
    accent: "green",
  },
  {
    id: "reports",
    title: "Gerar relatório completo",
    description: "Criador de frases + Anki Premium: evolução, erros recorrentes e exportação em Markdown.",
    path: "/reports",
    icon: "📝",
    kind: "tool",
    accent: "amber",
  },
];
