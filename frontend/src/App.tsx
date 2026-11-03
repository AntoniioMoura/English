import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { ClaudeSwitch } from "./components/ClaudeSwitch";
import { OllamaBadge } from "./components/OllamaBadge";
import { StudyClock } from "./components/StudyClock";
import { ExercisePage } from "./pages/ExercisePage";
import { FramePicker } from "./pages/FramePicker";
import { Home } from "./pages/Home";
import { ListeningEditor } from "./pages/listening/ListeningEditor";
import { ListeningLibrary } from "./pages/listening/ListeningLibrary";
import { ListeningPlayer } from "./pages/listening/ListeningPlayer";
import { ListeningStats } from "./pages/listening/ListeningStats";
import { ListeningVideo } from "./pages/listening/ListeningVideo";
import { Progress } from "./pages/Progress";
import { RecallHistory } from "./pages/recall/RecallHistory";
import { RecallHome } from "./pages/recall/RecallHome";
import { RecallPractice } from "./pages/recall/RecallPractice";
import { RecallReview } from "./pages/recall/RecallReview";
import { RecallWords } from "./pages/recall/RecallWords";
import { Reports } from "./pages/Reports";
import { StudyCalendar } from "./pages/StudyCalendar";

export default function App() {
  // Catálogo e player de vídeo pedem uma área mais larga que as telas de texto.
  const wide = useLocation().pathname.startsWith("/listening");
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden>
            EB
          </span>
          English Builder
        </Link>
        <nav>
          <NavLink to="/builder">Criador de frases</NavLink>
          <NavLink to="/recall">Anki Premium</NavLink>
          <NavLink to="/listening">Listening</NavLink>
          <NavLink to="/reports">Relatórios</NavLink>
        </nav>
        <OllamaBadge />
        <ClaudeSwitch />
        <StudyClock />
      </header>
      <main className={wide ? "content content-wide" : "content"}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/builder" element={<FramePicker />} />
          <Route path="/builder/:id" element={<ExercisePage />} />
          <Route path="/recall" element={<RecallHome />} />
          <Route path="/recall/practice" element={<RecallPractice />} />
          <Route path="/recall/review" element={<RecallReview />} />
          <Route path="/recall/words" element={<RecallWords />} />
          <Route path="/recall/history" element={<RecallHistory />} />
          <Route path="/listening" element={<ListeningLibrary />} />
          <Route path="/listening/stats" element={<ListeningStats />} />
          <Route path="/listening/video/:id" element={<ListeningVideo />} />
          <Route path="/listening/video/:id/edit" element={<ListeningEditor />} />
          <Route path="/listening/session/:id" element={<ListeningPlayer />} />
          <Route path="/progress" element={<Progress />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/study" element={<StudyCalendar />} />
          <Route path="*" element={<p>Página não encontrada.</p>} />
        </Routes>
      </main>
    </div>
  );
}
