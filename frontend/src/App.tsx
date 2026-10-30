import { Link, NavLink, Route, Routes } from "react-router-dom";
import { OllamaBadge } from "./components/OllamaBadge";
import { ExercisePage } from "./pages/ExercisePage";
import { FramePicker } from "./pages/FramePicker";
import { Home } from "./pages/Home";
import { Progress } from "./pages/Progress";
import { RecallHistory } from "./pages/recall/RecallHistory";
import { RecallHome } from "./pages/recall/RecallHome";
import { RecallPractice } from "./pages/recall/RecallPractice";
import { RecallReview } from "./pages/recall/RecallReview";
import { RecallWords } from "./pages/recall/RecallWords";
import { Reports } from "./pages/Reports";

export default function App() {
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
          <NavLink to="/reports">Relatórios</NavLink>
        </nav>
        <OllamaBadge />
      </header>
      <main className="content">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/builder" element={<FramePicker />} />
          <Route path="/builder/:id" element={<ExercisePage />} />
          <Route path="/recall" element={<RecallHome />} />
          <Route path="/recall/practice" element={<RecallPractice />} />
          <Route path="/recall/review" element={<RecallReview />} />
          <Route path="/recall/words" element={<RecallWords />} />
          <Route path="/recall/history" element={<RecallHistory />} />
          <Route path="/progress" element={<Progress />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="*" element={<p>Página não encontrada.</p>} />
        </Routes>
      </main>
    </div>
  );
}
