"""Agendador de revisão espaçada (MVP determinístico, substituível por FSRS).

O agendador só conhece o estado da unidade e o resultado; quem decide o que é
sucesso ou falha é o serviço, e a IA nunca define datas.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

INTERVAL_DAYS = [1, 3, 7, 14, 30]
RELEARN_DELAY = timedelta(0)  # errou a revisão: volta na hora, para o fim da fila de hoje
LAPSE_PENALTY = 0.15                  # cada erro reduz os próximos intervalos em 15%...
MIN_FACTOR = 0.3                      # ...até no máximo 70% (30 dias viram 9)
STABLE_MIN_SUCCESSES = 3      # retenção estável exige sucessos...
STABLE_MIN_DAYS = 3           # ...em dias diferentes, e nunca após um único acerto


@dataclass
class SchedulerState:
    step: int = -1                       # -1 = ainda não revisado com sucesso
    successes: int = 0
    lapses: int = 0
    success_days: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SchedulerState":
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)


class SimpleScheduler:
    name = "simple-v1"

    def on_created(self, now: datetime) -> tuple[SchedulerState, datetime]:
        """Dificuldade nova: já fica disponível em Revisar."""
        return SchedulerState(), now

    def on_reinforced(self, state: SchedulerState, due: datetime, now: datetime) -> tuple[SchedulerState, datetime]:
        """Mesmo erro de novo em frase nova: volta um passo e antecipa a revisão (no máximo 1 dia)."""
        state.step = max(state.step - 1, -1)
        return state, min(due, now + timedelta(days=1))

    def on_success(self, state: SchedulerState, now: datetime, local_day: str) -> tuple[SchedulerState, datetime]:
        state.step = min(state.step + 1, len(INTERVAL_DAYS) - 1)
        state.successes += 1
        if local_day not in state.success_days:
            state.success_days.append(local_day)
        return state, now + timedelta(days=self.interval_days(state))

    @staticmethod
    def interval_days(state: SchedulerState) -> int:
        """Cada erro acumulado encurta os intervalos futuros: a frase difícil volta com mais frequência."""
        factor = max(MIN_FACTOR, 1 - LAPSE_PENALTY * state.lapses)
        return max(1, round(INTERVAL_DAYS[state.step] * factor))

    def on_fail(self, state: SchedulerState, now: datetime) -> tuple[SchedulerState, datetime]:
        """Errou a revisão: volta para o fluxo de hoje (depois das outras pendentes), com outra frase.
        Só sai do dia quando acertar; aí recomeça pelo intervalo de 1 dia."""
        state.step = -1
        state.lapses += 1
        return state, now + RELEARN_DELAY

    def status(self, state: SchedulerState) -> str:
        if state.successes >= STABLE_MIN_SUCCESSES and len(state.success_days) >= STABLE_MIN_DAYS:
            return "stable"
        return "learning"


scheduler = SimpleScheduler()
